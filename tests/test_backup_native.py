import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from musicflow.api import create_app
from musicflow.database import Database
from musicflow.native import NativeBridge


@pytest.fixture
def data(tmp_path):
    database = Database(tmp_path / "data")
    with TestClient(create_app(database, "token"), headers={"X-MusicFlow-Token": "token"}) as client:
        project = client.post("/api/projects", json={"title": "Сохранённый трек", "notes": "Идея", "folder_path": "/tmp/Музыка с пробелами"}).json()
        client.post(f'/api/projects/{project["id"]}/tasks/template')
        yield database, client, tmp_path
    database.engine.dispose()


def test_backup_restore_safe_snapshot(data):
    database, client, tmp = data
    backup = tmp / "Копия с пробелами.sqlite3"
    database.backup(backup)
    Database.validate_backup(backup)
    client.post("/api/projects", json={"title": "После копии"})
    previous = database.restore(backup)
    assert previous.exists()
    projects = client.get("/api/projects").json()
    assert len(projects) == 1 and len(projects[0]["tasks"]) == 4
    with sqlite3.connect(previous) as connection:
        assert connection.execute("SELECT count(*) FROM projects").fetchone()[0] == 2


@pytest.mark.parametrize("damage", ["text", "version", "orphan", "trigger", "stage", "columns"])
def test_reject_bad_backup_keeps_original(data, damage):
    database, client, tmp = data
    backup = tmp / "bad.sqlite3"
    database.backup(backup)
    if damage == "text":
        backup.write_text("not sqlite")
    else:
        with sqlite3.connect(backup) as connection:
            if damage == "version": connection.execute("UPDATE alembic_version SET version_num='9999'")
            if damage == "orphan": connection.execute("UPDATE tasks SET project_id=9999")
            if damage == "trigger": connection.execute("CREATE TRIGGER bad AFTER INSERT ON projects BEGIN DELETE FROM tasks; END")
            if damage == "stage":
                connection.execute("PRAGMA ignore_check_constraints=ON")
                connection.execute("UPDATE projects SET status='unknown'")
            if damage == "columns": connection.execute("ALTER TABLE projects ADD COLUMN unknown TEXT")
    before = database.path.read_bytes()
    with pytest.raises(ValueError): database.restore(backup)
    assert database.path.read_bytes() == before
    assert client.get("/api/projects").json()[0]["title"] == "Сохранённый трек"


def test_cannot_backup_or_restore_over_current(data):
    database, _, _ = data
    with pytest.raises(ValueError): database.backup(database.path)
    with pytest.raises(ValueError): database.restore(database.path)


def test_native_dialog_cancellation_missing_folder_and_safe_open(data):
    database, client, tmp = data
    bridge = NativeBridge(database)
    bridge._window = Mock()
    bridge._window.create_file_dialog.return_value = None
    assert bridge.choose_folder()["cancelled"]
    assert bridge.export_backup()["cancelled"]
    assert bridge.prepare_restore()["cancelled"]
    assert not bridge.restore_backup()["ok"]
    assert bridge.open_project_folder(1)["missing"]
    folder = tmp / "Музыка с пробелами"
    folder.mkdir()
    client.patch("/api/projects/1", json={"folder_path": str(folder)})
    with patch("musicflow.native.subprocess.run") as run:
        assert bridge.open_project_folder(1)["ok"]
        assert run.call_args.args[0] == ["/usr/bin/open", "--", str(folder)]
    client.delete("/api/projects/1")
    assert folder.is_dir()


def test_restore_revalidates_file_after_confirmation(data):
    database, _, tmp = data
    source = tmp / "changed.sqlite3"
    database.backup(source)
    bridge = NativeBridge(database)
    bridge._window = Mock()
    bridge._window.create_file_dialog.return_value = (str(source),)
    assert bridge.prepare_restore()["ok"]
    source.write_text("changed after dialog")
    assert not bridge.restore_backup()["ok"]


@pytest.mark.parametrize("as_string", [True, False])
def test_native_export_handles_cocoa_string_and_tuple(data, as_string):
    database, _, tmp = data
    destination = tmp / "Копия с пробелами.sqlite3"
    bridge = NativeBridge(database)
    bridge._window = Mock()
    bridge._window.create_file_dialog.return_value = str(destination) if as_string else (str(destination),)
    assert bridge.export_backup()["ok"]
    Database.validate_backup(destination)
    bridge._window.show.assert_called_once()
