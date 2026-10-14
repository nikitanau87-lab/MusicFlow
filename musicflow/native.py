import logging
import subprocess
from datetime import datetime
from pathlib import Path

import webview

from .database import Database
from .models import Project
from .files import AUDIO_TYPES, DAW_EXTENSIONS


class NativeBridge:
    def __init__(self, database: Database):
        self._database = database
        self._pending_restore = None
        self._window = None

    def set_dirty(self, dirty: bool):
        self._window.confirm_close = bool(dirty)
        return {"ok": True}

    def _dialog(self, kind, **options):
        try:
            selection = self._window.create_file_dialog(kind, **options)
            # Cocoa's save panel returns a string, while its open panel returns
            # a tuple (despite the common API's tuple annotation).
            return (selection,) if isinstance(selection, str) else selection
        finally:
            # Restore the main window's focus after Cocoa closes its modal panel.
            self._window.show()

    def choose_folder(self):
        try:
            selected = self._dialog(webview.FileDialog.FOLDER)
            return {"ok": True, "value": selected[0] if selected else None, "cancelled": not bool(selected)}
        except Exception:
            logging.getLogger("musicflow").exception("Folder chooser failed")
            return {"ok": False, "error": "Не удалось открыть выбор папки."}

    def choose_daw_file(self, project_id: int):
        return self._choose_project_file(project_id, False)

    def choose_audio_file(self, project_id: int):
        return self._choose_project_file(project_id, True)

    def _choose_project_file(self, project_id, audio):
        try:
            with self._database.lock, self._database.session() as db:
                project = db.get(Project, int(project_id))
                directory = project.folder_path if project else None
            filters = ("Аудиофайлы (*.wav;*.mp3;*.m4a;*.aif;*.aiff;*.flac;*.aac)",) if audio else ("Проекты DAW (*.flp;*.als;*.logicx;*.rpp;*.band;*.song;*.cpr;*.ptx)",)
            selected = self._dialog(webview.FileDialog.OPEN, directory=directory or "", allow_multiple=False, file_types=filters)
            if not selected:
                return {"ok": True, "cancelled": True}
            path = Path(selected[0])
            extensions = AUDIO_TYPES if audio else DAW_EXTENSIONS
            if path.suffix.lower() not in extensions:
                return {"ok": False, "error": "Выберите поддерживаемый аудиофайл." if audio else "Выберите файл проекта DAW."}
            return {"ok": True, "value": str(path), "folder": str(path.parent)}
        except Exception:
            logging.getLogger("musicflow").exception("Project file chooser failed")
            return {"ok": False, "error": "Не удалось выбрать файл. Повторите попытку."}

    def open_daw_project(self, project_id: int):
        try:
            with self._database.lock, self._database.session() as db:
                project = db.get(Project, int(project_id))
                path = Path(project.daw_path) if project and project.daw_path else None
            if path is None or path.suffix.lower() not in DAW_EXTENSIONS or not (path.is_file() or path.suffix.lower() in {".logicx", ".band"} and path.is_dir()):
                return {"ok": False, "missing": True, "error": "Файл проекта DAW недоступен. Выберите его заново."}
            args = ["/usr/bin/open"]
            if path.suffix.lower() == ".flp":
                args.extend(["-b", "com.image-line.flstudio"])
            args.extend(["--", str(path)])
            subprocess.run(args, check=True, timeout=10, capture_output=True)
            return {"ok": True}
        except Exception:
            logging.getLogger("musicflow").exception("Opening DAW failed")
            return {"ok": False, "error": "Не удалось открыть проект. Проверьте, что нужная DAW установлена на Mac."}

    def open_project_folder(self, project_id: int):
        try:
            with self._database.lock, self._database.session() as db:
                project = db.get(Project, int(project_id))
                folder = project.folder_path if project else None
            if not folder or not Path(folder).is_dir():
                return {"ok": False, "missing": True, "error": "Папка недоступна. Возможно, она перемещена или внешний диск отключён. Выберите папку заново."}
            subprocess.run(["/usr/bin/open", "--", folder], check=True, timeout=10, capture_output=True)
            return {"ok": True}
        except Exception:
            logging.getLogger("musicflow").exception("Opening folder failed")
            return {"ok": False, "error": "Не удалось открыть папку в Finder."}

    def export_backup(self):
        try:
            selected = self._dialog(webview.FileDialog.SAVE, save_filename=f"MusicFlow-{datetime.now():%Y-%m-%d}.sqlite3", file_types=("База MusicFlow (*.sqlite3)",))
            if not selected:
                return {"ok": True, "cancelled": True}
            destination = Path(selected[0])
            if destination.suffix != ".sqlite3":
                destination = destination.with_suffix(".sqlite3")
                if destination.exists() and not self._window.create_confirmation_dialog("Файл существует", "Заменить существующую резервную копию?"):
                    return {"ok": True, "cancelled": True}
            self._database.backup(destination)
            return {"ok": True, "value": destination.name}
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except Exception:
            logging.getLogger("musicflow").exception("Backup failed")
            return {"ok": False, "error": "Не удалось сохранить копию. Проверьте доступ к выбранной папке."}

    def prepare_restore(self):
        self._pending_restore = None
        try:
            selected = self._dialog(webview.FileDialog.OPEN, allow_multiple=False, file_types=("База MusicFlow (*.sqlite3)", "Все файлы (*.*)"))
            if not selected:
                return {"ok": True, "cancelled": True}
            source = Path(selected[0])
            Database.validate_backup(source)
            if source.resolve() == self._database.path.resolve():
                raise ValueError("Выберите резервную копию, а не рабочую базу.")
            self._pending_restore = source
            return {"ok": True, "value": source.name}
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except Exception:
            logging.getLogger("musicflow").exception("Reading backup failed")
            return {"ok": False, "error": "Не удалось открыть резервную копию."}

    def restore_backup(self):
        source = self._pending_restore
        self._pending_restore = None
        if source is None:
            return {"ok": False, "error": "Сначала выберите резервную копию."}
        try:
            self._database.restore(source)
            return {"ok": True}
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except Exception:
            logging.getLogger("musicflow").exception("Restore failed")
            return {"ok": False, "error": "Не удалось восстановить копию. Текущие данные сохранены."}
