import os
import json
import sqlite3
import threading
import tempfile
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from .models import Base, STAGES, EVENT_KINDS

REVISION = "0003"
LEGACY_PROJECT_COLUMNS = {"id", "title", "bpm", "musical_key", "genre", "status", "notes", "folder_path", "archived", "created_at", "updated_at"}


class Database:
    """Serializes short DB operations and swaps restored databases atomically."""
    def __init__(self, directory: Path):
        self.directory = directory
        self.generation = 0
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "musicflow.sqlite3"
        # FastAPI may enter and exit sync dependencies on different threads.
        self.lock = threading.Lock()
        self.engine = self._engine()
        self._migrate()

    def _engine(self):
        engine = create_engine(f"sqlite:///{self.path}", connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
        return engine

    def _migrate(self):
        if self.path.exists() and self.path.stat().st_size:
            with sqlite3.connect(self.path) as connection:
                row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if not row or row[0] != REVISION:
                self.safety_backup("before-migration")
        self._upgrade(self.engine)

    @staticmethod
    def _upgrade(engine):
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def session(self):
        return Session(self.engine, expire_on_commit=False)

    def backup(self, destination: Path):
        with self.lock:
            self._backup(destination)

    def _backup(self, destination: Path):
        if destination.resolve() == self.path.resolve():
            raise ValueError("Выберите другое место: нельзя заменить рабочую базу её копией.")
        with tempfile.NamedTemporaryFile(prefix=".musicflow-", suffix=".partial", dir=destination.parent, delete=False) as file:
            temporary = Path(file.name)
        try:
            with sqlite3.connect(self.path) as source, sqlite3.connect(temporary) as target:
                source.backup(target)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def safety_backup(self, reason: str):
        with self.lock:
            return self._safety_backup(reason)

    def _safety_backup(self, reason: str):
        folder = self.directory / "backups"
        folder.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = folder / f"{stamp}-{reason}.sqlite3"
        self._backup(destination)
        return destination

    @staticmethod
    def validate_backup(path: Path):
        try:
            with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
                connection.execute("PRAGMA query_only=ON")
                if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Резервная копия повреждена.")
                objects = connection.execute("SELECT name, type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
                tables = {name for name, kind in objects if kind == "table"}
                if any(kind in {"view", "trigger"} for _, kind in objects) or "alembic_version" not in tables:
                    raise ValueError("Этот файл не является резервной копией MusicFlow.")
                revisions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
                if revisions not in [[("0001",)], [("0002",)], [(REVISION,)]]:
                    raise ValueError("Версия резервной копии не поддерживается этой версией MusicFlow.")
                revision = revisions[0][0]
                expected_tables = {"projects", "tasks", "alembic_version"} if revision == "0001" else (set(Base.metadata.tables) - ({"activity_events"} if revision == "0002" else set())) | {"alembic_version"}
                if tables != expected_tables:
                    raise ValueError("Этот файл не является резервной копией MusicFlow.")
                for table in Base.metadata.sorted_tables:
                    if table.name not in tables:
                        continue
                    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table.name})")}
                    expected = LEGACY_PROJECT_COLUMNS if table.name == "projects" and revision == "0001" else set(table.columns.keys())
                    if table.name == "projects" and revision == "0002":
                        expected = expected - {"file_history_state"}
                    if columns != expected:
                        raise ValueError("Структура резервной копии не соответствует MusicFlow.")
                if connection.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("В резервной копии нарушены связи проектов и задач.")
                connection.row_factory = sqlite3.Row
                for row in connection.execute("SELECT * FROM projects"):
                    if not isinstance(row["title"], str) or not row["title"].strip() or len(row["title"]) > 200:
                        raise ValueError("В резервной копии некорректные проекты.")
                    if row["status"] not in STAGES or row["archived"] not in (0, 1):
                        raise ValueError("В резервной копии некорректные стадии проектов.")
                    if row["bpm"] is not None and (not isinstance(row["bpm"], (int, float)) or not 0 < row["bpm"] < float("inf")):
                        raise ValueError("В резервной копии некорректный BPM.")
                    if not isinstance(row["notes"], str) or len(row["notes"]) > 100000:
                        raise ValueError("В резервной копии некорректные заметки.")
                    optional_fields = [("musical_key", 40), ("genre", 100), ("folder_path", 4096)]
                    if revision != "0001":
                        optional_fields.extend((("daw_path", 4096), ("preview_path", 4096)))
                        tags = json.loads(row["tags"])
                        if not isinstance(tags, list) or len(tags) > 30 or any(not isinstance(tag, str) or not tag.strip() or len(tag) > 48 for tag in tags) or len({tag.casefold() for tag in tags}) != len(tags):
                            raise ValueError("В резервной копии некорректные теги.")
                        for flag in ("preview_auto", "folder_scan_partial", "folder_unavailable"):
                            if row[flag] not in (0, 1):
                                raise ValueError("В резервной копии некорректные параметры файлов.")
                        for number in ("folder_size_bytes", "folder_file_count"):
                            if row[number] is not None and (not isinstance(row[number], int) or row[number] < 0):
                                raise ValueError("В резервной копии некорректный размер папки.")
                        for stamp in ("last_worked_at", "folder_scanned_at"):
                            if row[stamp] is not None:
                                try:
                                    datetime.fromisoformat(row[stamp])
                                except ValueError as error:
                                    raise ValueError("В резервной копии некорректные даты файлов.") from error
                    for field, maximum in optional_fields:
                        if row[field] is not None and (not isinstance(row[field], str) or len(row[field]) > maximum):
                            raise ValueError("В резервной копии некорректные параметры проекта.")
                    for field in ("created_at", "updated_at"):
                        try:
                            datetime.fromisoformat(row[field])
                        except ValueError as error:
                            raise ValueError("В резервной копии некорректные даты проектов.") from error
                project_ids = {row[0] for row in connection.execute("SELECT id FROM projects")}
                positions = {}
                for row in connection.execute("SELECT * FROM tasks"):
                    if row["project_id"] not in project_ids or not isinstance(row["title"], str) or not row["title"].strip() or len(row["title"]) > 300 or row["completed"] not in (0, 1):
                        raise ValueError("В резервной копии некорректные задачи.")
                    positions.setdefault(row["project_id"], []).append(row["position"])
                if any(sorted(values) != list(range(len(values))) for values in positions.values()):
                    raise ValueError("В резервной копии некорректный порядок задач.")
                if revision != "0001":
                    collection_ids = set()
                    names = set()
                    for row in connection.execute("SELECT * FROM collections"):
                        if not isinstance(row["name"], str) or not row["name"].strip() or len(row["name"]) > 80 or row["normalized_name"] != row["name"].casefold() or row["normalized_name"] in names:
                            raise ValueError("В резервной копии некорректные подборки.")
                        names.add(row["normalized_name"])
                        collection_ids.add(row["id"])
                    for row in connection.execute("SELECT * FROM project_collections"):
                        if row["project_id"] not in project_ids or row["collection_id"] not in collection_ids:
                            raise ValueError("В резервной копии нарушены связи подборок.")
                if revision == REVISION:
                    for row in connection.execute("SELECT * FROM projects"):
                        state = json.loads(row["file_history_state"]) if row["file_history_state"] else None
                        if state is not None and (not isinstance(state, dict) or len(state) > 2 or any(key not in {"daw", "demo"} or not isinstance(value, dict) or set(value) != {"path", "mtime", "size"} or not isinstance(value["path"], str) or not isinstance(value["mtime"], (int, float)) or not 0 <= value["mtime"] < float("inf") or not isinstance(value["size"], int) or value["size"] < 0 for key, value in state.items())):
                            raise ValueError("В резервной копии некорректная история файлов.")
                    for row in connection.execute("SELECT * FROM activity_events"):
                        if row["project_id"] not in project_ids or row["kind"] not in EVENT_KINDS or not isinstance(row["summary"], str) or not row["summary"].strip() or len(row["summary"]) > 5000:
                            raise ValueError("В резервной копии некорректные события.")
                        if not isinstance(json.loads(row["details"]), dict) or len(row["details"]) > 50000:
                            raise ValueError("В резервной копии некорректные подробности событий.")
                        duration = row["duration_minutes"]
                        if duration is not None and (row["kind"] != "manual" or not isinstance(duration, int) or not 1 <= duration <= 1440):
                            raise ValueError("В резервной копии некорректная длительность работы.")
                        for stamp in ("occurred_at", "recorded_at"):
                            datetime.fromisoformat(row[stamp])
                return revision
        except json.JSONDecodeError as error:
            raise ValueError("В резервной копии некорректные теги.") from error
        except (sqlite3.Error, TypeError, OverflowError) as error:
            raise ValueError("Не удалось прочитать резервную копию MusicFlow.") from error

    def restore(self, source: Path):
        with self.lock:
            if source.resolve() == self.path.resolve():
                raise ValueError("Выберите файл резервной копии, а не текущую базу.")
            self.validate_backup(source)
            staged = self.directory / "restore.partial"
            try:
                with sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True) as origin, sqlite3.connect(staged) as target:
                    origin.backup(target)
                self.validate_backup(staged)
                staged_engine = create_engine(f"sqlite:///{staged}")
                try:
                    self._upgrade(staged_engine)
                finally:
                    staged_engine.dispose()
                self.validate_backup(staged)
                previous = self._safety_backup("before-restore")
                self.engine.dispose()
                os.replace(staged, self.path)
                self.engine = self._engine()
                self.generation += 1
                return previous
            finally:
                staged.unlink(missing_ok=True)
