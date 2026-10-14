"""Read-only inspection of a project folder; no copying or DAW parsing."""
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .models import Project, now
from .history import record

DAW_EXTENSIONS = {".flp", ".als", ".logicx", ".rpp", ".band", ".song", ".cpr", ".ptx"}
AUDIO_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aif": "audio/aiff", ".aiff": "audio/aiff", ".flac": "audio/flac", ".aac": "audio/aac"}
DEMO_WORDS = re.compile(r"demo|демо|демка|preview|rough|черновик|bounce|mixdown", re.IGNORECASE)
EXPORT_FOLDERS = {"exports", "export", "renders", "render", "bounces", "demos", "demo", "демки", "экспорты", "mixes"}


def inspect_folder(folder: str | None, daw: str | None, stop: threading.Event | None = None):
    result = {"size": None, "count": 0, "partial": False, "unavailable": False, "last_worked_at": None, "daw_path": daw, "audio": [], "error": None}
    started = time.monotonic()
    latest_daw = None
    main_daw_time = None
    if daw:
        try:
            main_daw_time = Path(daw).stat().st_mtime
        except OSError:
            pass
    if not folder:
        if main_daw_time is not None:
            result["last_worked_at"] = datetime.fromtimestamp(main_daw_time, timezone.utc)
        return result
    root = Path(folder)
    if not root.is_dir():
        result["unavailable"] = True
        result["error"] = "Папка недоступна. Проверьте путь или подключение диска."
        if main_daw_time is not None:
            result["last_worked_at"] = datetime.fromtimestamp(main_daw_time, timezone.utc)
        return result
    result["size"] = 0
    directories = [root]
    visited = 0
    while directories:
        if (stop and stop.is_set()) or time.monotonic() - started > 30 or visited >= 100000:
            result["partial"] = True
            break
        directory = directories.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    visited += 1
                    if (stop and stop.is_set()) or visited > 100000 or time.monotonic() - started > 30:
                        result["partial"] = True
                        directories.clear()
                        break
                    try:
                        if entry.is_symlink():
                            result["partial"] = True
                            continue
                        path = Path(entry.path)
                        stat = entry.stat(follow_symlinks=False)
                        if path.suffix.lower() in DAW_EXTENSIONS:
                            if not daw and (latest_daw is None or stat.st_mtime > latest_daw):
                                result["daw_path"] = str(path)
                            latest_daw = max(latest_daw or stat.st_mtime, stat.st_mtime)
                        if entry.is_dir(follow_symlinks=False):
                            directories.append(path)
                        elif entry.is_file(follow_symlinks=False):
                            result["size"] += stat.st_size
                            result["count"] += 1
                            if path.suffix.lower() in AUDIO_TYPES and stat.st_size > 0:
                                relative = path.relative_to(root)
                                score = 100 if DEMO_WORDS.search(path.stem) else 0
                                if any(part.casefold() in EXPORT_FOLDERS for part in relative.parts[:-1]):
                                    score += 50
                                if path.stem.casefold() in {root.name.casefold(), Path(daw).stem.casefold() if daw else ""}:
                                    score += 80
                                result["audio"].append({"path": str(path), "name": str(relative), "mtime": stat.st_mtime, "size": stat.st_size, "score": score})
                                if len(result["audio"]) > 200:
                                    result["audio"] = sorted(result["audio"], key=lambda a: (a["score"], a["mtime"], a["path"]), reverse=True)[:100]
                    except OSError:
                        result["partial"] = True
        except OSError:
            result["partial"] = True
    result["audio"] = sorted(result["audio"], key=lambda a: (a["score"], a["mtime"], a["path"]), reverse=True)[:100]
    timestamp = main_daw_time if daw else latest_daw
    if timestamp is not None:
        result["last_worked_at"] = datetime.fromtimestamp(timestamp, timezone.utc)
    if result["partial"]:
        result["error"] = "Размер рассчитан частично: некоторые файлы недоступны, являются ссылками или достигнут предел сканирования."
    return result


class FolderScanner:
    def __init__(self, database):
        self.database = database
        self._guard = threading.Lock()
        self._jobs = {}
        self._stop = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="musicflow-files")

    def close(self):
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def get(self, project_id: int, refresh: bool = False):
        with self.database.lock, self.database.session() as db:
            project = db.get(Project, project_id)
            if project is None:
                raise KeyError(project_id)
            signature = (project.folder_path, project.daw_path, project.created_at, self.database.generation)
        if not signature[0] and not signature[1]:
            return {"state": "empty", "audio": [], "error": None}
        with self._guard:
            job = self._jobs.get(project_id)
            if job and job["signature"] == signature and (job["state"] == "pending" or not refresh and time.monotonic() - job["finished"] < 60):
                return {key: job[key] for key in ("state", "audio", "error")}
            previous_audio = job["audio"] if job and job["signature"] == signature else []
            job = {"signature": signature, "state": "pending", "audio": previous_audio, "error": None, "finished": 0}
            self._jobs[project_id] = job
            if not self._stop.is_set():
                self._pool.submit(self._scan, project_id, job)
            return {"state": "pending", "audio": previous_audio, "error": None}

    def _scan(self, project_id, job):
        signature = job["signature"]
        try:
            info = inspect_folder(signature[0], signature[1], self._stop)
            if self._stop.is_set():
                return
            with self.database.lock, self.database.session() as db:
                project = db.get(Project, project_id)
                if not project or (project.folder_path, project.daw_path, project.created_at, self.database.generation) != signature:
                    with self._guard:
                        job.update(state="empty", finished=time.monotonic())
                    return
                project.folder_size_bytes = info["size"]
                project.folder_file_count = info["count"]
                project.folder_scan_partial = info["partial"]
                project.folder_unavailable = info["unavailable"]
                project.folder_scanned_at = now()
                project.last_worked_at = info["last_worked_at"]
                if project.preview_auto and not info["unavailable"]:
                    # A plain sample is listed for selection, but never guessed as a demo.
                    project.preview_path = next((item["path"] for item in info["audio"] if item["score"] > 0), None)
                if not info["unavailable"]:
                    current = {}
                    for key, path in (("daw", info["daw_path"]), ("demo", project.preview_path)):
                        if path:
                            try:
                                stat = Path(path).stat()
                                if stat.st_mtime >= 0:
                                    current[key] = {"path": path, "mtime": stat.st_mtime, "size": stat.st_size}
                            except OSError:
                                pass
                    before = project.file_history_state
                    if before is not None:
                        for key, value in current.items():
                            previous = before.get(key)
                            if previous != value:
                                label = "Обнаружено сохранение DAW" if key == "daw" else "Обнаружена новая или обновлённая демка"
                                timestamp = min(datetime.fromtimestamp(value["mtime"], timezone.utc), now())
                                record(project, "daw_saved" if key == "daw" else "demo_updated", f"{label}: {Path(value['path']).name}", {"file": value["path"], "mtime": value["mtime"], "source": "file_observation"}, occurred_at=timestamp)
                    # Missing files keep their previous baseline until they reappear.
                    project.file_history_state = {**(before or {}), **current}
                db.commit()
            with self._guard:
                if self._jobs.get(project_id) is job:
                    job.update(state="missing" if info["unavailable"] else "partial" if info["partial"] else "ready", audio=info["audio"], error=info["error"], finished=time.monotonic())
        except Exception:
            import logging
            logging.getLogger("musicflow").exception("Folder scan failed")
            with self._guard:
                job.update(state="error", error="Не удалось проверить папку проекта.", finished=time.monotonic())

    def refresh_all(self):
        from sqlalchemy import select
        with self.database.lock, self.database.session() as db:
            identifiers = list(db.scalars(select(Project.id).where(Project.folder_path.is_not(None) | Project.daw_path.is_not(None))))
        for identifier in identifiers:
            try:
                self.get(identifier, refresh=True)
            except KeyError:
                pass
        return self.pending()

    def pending(self):
        with self._guard:
            return sum(job["state"] == "pending" for job in self._jobs.values())
