"""Native entry point; the server and window share one application lifetime."""
import fcntl
import logging
from logging.handlers import RotatingFileHandler
import os
import socket
import threading
import time
from pathlib import Path

import uvicorn
import webview

from musicflow.api import create_app
from musicflow.database import Database
from musicflow.native import NativeBridge


def main():
    directory = Path(os.environ.get("MUSICFLOW_DATA_DIR", Path.home() / "Library/Application Support/MusicFlow")).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / "app.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    logger = logging.getLogger("musicflow")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(directory / "musicflow.log", maxBytes=1_000_000, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    database = None
    try:
        database = Database(directory)
        run_window(database)
    except Exception:
        logger.exception("Application failed to start")
        # A native error is useful even if the HTTP server or database cannot start.
        import AppKit
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("Не удалось открыть MusicFlow")
        alert.setInformativeText_("Данные сохранены. Подробности находятся в журнале MusicFlow в папке Application Support.")
        alert.runModal()
    finally:
        if database:
            database.engine.dispose()
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def run_window(database):
    assets = Path(__file__).resolve().parent / "frontend" / "dist"
    app = create_app(database, webview.token, assets)
    bridge = NativeBridge(database)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", log_level="warning", log_config=None, lifespan="off", ws="none"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not worker.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Local server did not start")
            time.sleep(.05)
        window = webview.create_window("MusicFlow", f"http://127.0.0.1:{listener.getsockname()[1]}", js_api=bridge, width=1380, height=880, min_size=(760, 580), background_color="#111116", text_select=True)
        bridge._window = window

        # Cocoa's closing callback runs on the main thread. Calling evaluate_js
        # there blocks that same thread. The bridge updates confirm_close instead.
        window.confirm_close = True
        webview.start(gui="cocoa", localization={
            "global.quitConfirmation": "Есть несохранённые изменения. Выйти без сохранения?",
            "global.quit": "Выйти", "global.cancel": "Отмена", "global.ok": "Продолжить",
            "cocoa.menu.about": "О MusicFlow", "cocoa.menu.services": "Службы",
            "cocoa.menu.view": "Вид", "cocoa.menu.edit": "Правка", "cocoa.menu.hide": "Скрыть MusicFlow",
            "cocoa.menu.hideOthers": "Скрыть остальные", "cocoa.menu.showAll": "Показать все",
            "cocoa.menu.quit": "Выйти из MusicFlow", "cocoa.menu.fullscreen": "На весь экран",
            "cocoa.menu.cut": "Вырезать", "cocoa.menu.copy": "Скопировать",
            "cocoa.menu.paste": "Вставить", "cocoa.menu.selectAll": "Выбрать всё",
        })
    finally:
        app.state.scanner.close()
        server.should_exit = True
        worker.join(timeout=5)
        listener.close()


if __name__ == "__main__":
    main()
