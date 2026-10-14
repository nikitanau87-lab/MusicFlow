from setuptools import setup
from py2app.build_app import py2app
import zlib


class MusicFlowBuild(py2app):
    """py2app 0.28 assumes zlib is a dylib; standalone CPython embeds it."""
    def build_executable(self, *args, **kwargs):
        builtin = not hasattr(zlib, "__file__")
        if builtin:
            zlib.__file__ = "__musicflow_builtin_zlib__"
        try:
            return super().build_executable(*args, **kwargs)
        finally:
            if builtin:
                del zlib.__file__

    def copy_file(self, source, destination, *args, **kwargs):
        if source == "__musicflow_builtin_zlib__":
            return destination, False
        return super().copy_file(source, destination, *args, **kwargs)

setup(
    name="MusicFlow",
    version="0.3.0",
    app=["desktop.py"],
    cmdclass={"py2app": MusicFlowBuild},
    options={"py2app": {
        "argv_emulation": False,
        "iconfile": "assets/MusicFlow.icns",
        "packages": ["musicflow", "webview", "fastapi", "uvicorn", "sqlalchemy", "alembic", "anyio"],
        "includes": ["anyio._backends._asyncio", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl", "sqlalchemy.dialects.sqlite.pysqlite", "webview.platforms.cocoa", "alembic.ddl.sqlite"],
        "resources": [("frontend", ["frontend/dist"])],
        "excludes": ["pytest", "PIL", "tkinter", "PyQt5", "PyQt6", "PySide6"],
        "plist": {"CFBundleName": "MusicFlow", "CFBundleDisplayName": "MusicFlow", "CFBundleIdentifier": "local.musicflow.app", "NSHighResolutionCapable": True},
    }},
)
