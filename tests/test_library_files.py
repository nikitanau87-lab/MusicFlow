import os
import sqlite3
import time
import wave
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from musicflow.api import create_app
from musicflow.database import Database
from musicflow.files import inspect_folder
from musicflow.native import NativeBridge


@pytest.fixture
def library(tmp_path):
    database = Database(tmp_path / "data")
    app = create_app(database, "test-token")
    with TestClient(app, headers={"X-MusicFlow-Token": "test-token"}) as client:
        yield client, database, tmp_path, app
    database.engine.dispose()


def audio(path: Path, frames=8000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(8000)
        file.writeframes(b"\0\0" * frames)


def scan(client, identifier, refresh=False):
    deadline = time.monotonic() + 5
    response = client.get(f"/api/projects/{identifier}/folder-info", params={"refresh": refresh})
    assert response.status_code == 200, response.text
    result = response.json()
    while result["state"] == "pending":
        assert time.monotonic() < deadline, result
        time.sleep(.01)
        result = client.get(f"/api/projects/{identifier}/folder-info").json()
    return result


def test_tags_and_many_to_many_collections(library):
    client, database, _, _ = library
    one = client.post("/api/collections", json={"name": " Первый   EP "}).json()
    two = client.post("/api/collections", json={"name": "Идеи"}).json()
    assert one["name"] == "Первый EP"
    assert client.post("/api/collections", json={"name": "первый EP"}).status_code == 409
    project = client.post("/api/projects", json={"title": "Трек", "tags": ["#Ночь", "ночь", " House "], "collection_ids": [one["id"], two["id"], one["id"]]}).json()
    assert project["tags"] == ["Ночь", "House"] and len(project["collections"]) == 2
    assert len(client.get("/api/projects", params={"tag": "НОЧЬ", "collection_id": one["id"]}).json()) == 1
    assert client.get("/api/projects?tag=неизвестный").json() == []
    assert client.patch(f'/api/projects/{project["id"]}', json={"collection_ids": [9999]}).status_code == 422
    assert client.post("/api/projects", json={"title": "x", "tags": ["x" * 49]}).status_code == 422
    client.patch(f'/api/collections/{one["id"]}', json={"name": "Релиз"})
    assert "Релиз" in [item["name"] for item in client.get(f'/api/projects/{project["id"]}').json()["collections"]]
    client.delete(f'/api/collections/{one["id"]}')
    assert client.get(f'/api/projects/{project["id"]}').status_code == 200
    assert client.get(f'/api/projects/{project["id"]}').json()["collection_ids"] == [two["id"]]
    client.delete(f'/api/projects/{project["id"]}')
    assert client.get("/api/collections").json()[0]["project_count"] == 0


def test_folder_size_real_daw_date_demo_selection_and_refresh(library):
    client, _, tmp, _ = library
    folder = tmp / "Музыка с пробелами"
    folder.mkdir()
    daw = folder / "track.flp"
    daw.write_bytes(b"FLhd-test")
    os.utime(daw, (1700000000, 1700000000))
    audio(folder / "samples" / "kick.wav")
    audio(folder / "exports" / "демо 01.wav")
    audio(folder / "exports" / "демо 02.wav")
    os.utime(folder / "exports" / "демо 01.wav", (1700000100, 1700000100))
    os.utime(folder / "exports" / "демо 02.wav", (1700000200, 1700000200))
    project = client.post("/api/projects", json={"title": "Track", "folder_path": str(folder), "daw_path": str(daw)}).json()
    info = scan(client, project["id"])
    assert info["state"] == "ready"
    assert info["project"]["folder_size_bytes"] == sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())
    assert info["project"]["folder_file_count"] == 4
    assert info["project"]["preview_path"].endswith("демо 02.wav")
    assert info["project"]["last_worked_at"] == "2023-11-14T22:13:20Z"
    assert info["project"]["updated_at"] == project["updated_at"]
    client.patch(f'/api/projects/{project["id"]}', json={"notes": "Правка заметок"})
    assert client.get(f'/api/projects/{project["id"]}').json()["last_worked_at"] == info["project"]["last_worked_at"]
    audio(folder / "exports" / "demo 03.wav", frames=16000)
    info = scan(client, project["id"], True)
    assert info["project"]["preview_path"].endswith("demo 03.wav")
    chosen = str(folder / "exports" / "демо 01.wav")
    client.patch(f'/api/projects/{project["id"]}', json={"preview_path": chosen, "preview_auto": False})
    assert scan(client, project["id"], True)["project"]["preview_path"] == chosen


def test_samples_are_not_guessed_as_demo_and_symlinks_not_followed(library):
    client, _, tmp, _ = library
    folder = tmp / "root"
    audio(folder / "samples" / "kick.wav")
    external = tmp / "external"
    audio(external / "demo.wav")
    (folder / "link").symlink_to(external, target_is_directory=True)
    info = inspect_folder(str(folder), None)
    assert info["count"] == 1 and info["partial"]
    project = client.post("/api/projects", json={"title": "Track", "folder_path": str(folder)}).json()
    assert scan(client, project["id"])["project"]["preview_path"] is None
    assert scan(client, project["id"])["audio"][0]["name"] == "samples/kick.wav"


def test_unavailable_folder_and_no_daw_do_not_invent_work_date(library):
    client, _, tmp, _ = library
    project = client.post("/api/projects", json={"title": "Track", "folder_path": str(tmp / "missing")}).json()
    info = scan(client, project["id"])
    assert info["state"] == "missing"
    assert info["project"]["folder_unavailable"]
    assert info["project"]["folder_size_bytes"] is None
    assert info["project"]["last_worked_at"] is None
    audio(tmp / "just-audio" / "demo.wav")
    assert inspect_folder(str(tmp / "just-audio"), None)["last_worked_at"] is None
    (tmp / "just-audio" / "other.flp").write_bytes(b"test")
    assert inspect_folder(str(tmp / "just-audio"), str(tmp / "missing.flp"))["last_worked_at"] is None


def test_audio_cookie_auth_range_seeking_and_missing_files(library):
    client, _, tmp, app = library
    path = tmp / "Демо с пробелами.wav"
    audio(path)
    project = client.post("/api/projects", json={"title": "Track", "preview_path": str(path), "preview_auto": False}).json()
    endpoint = f'/api/projects/{project["id"]}/audio'
    with TestClient(app) as outsider:
        assert outsider.get(endpoint).status_code == 403
        assert outsider.post("/api/media-session").status_code == 403
        session = outsider.post("/api/media-session", headers={"X-MusicFlow-Token": "test-token"})
        assert "HttpOnly" in session.headers["set-cookie"] and "SameSite=strict" in session.headers["set-cookie"]
        response = outsider.get(endpoint, headers={"Range": "bytes=0-15"})
        assert response.status_code == 206 and response.content == path.read_bytes()[:16]
        assert response.headers["accept-ranges"] == "bytes" and response.headers["content-type"] == "audio/wav"
    assert client.get(endpoint, headers={"Range": "bytes=999999-"}).status_code == 416
    assert client.patch(f'/api/projects/{project["id"]}', json={"preview_path": str(tmp / "notes.txt")}).status_code == 422
    path.unlink()
    assert client.get(endpoint).status_code == 404


def test_daw_chooser_and_safe_open_command(library):
    client, database, tmp, _ = library
    path = tmp / "DAW с пробелами.flp"
    path.write_bytes(b"test")
    project = client.post("/api/projects", json={"title": "Track", "daw_path": str(path)}).json()
    bridge = NativeBridge(database)
    bridge._window = Mock()
    bridge._window.create_file_dialog.return_value = (str(path),)
    assert bridge.choose_daw_file(project["id"])["value"] == str(path)
    with patch("musicflow.native.subprocess.run") as run:
        assert bridge.open_daw_project(project["id"])["ok"]
        assert run.call_args.args[0] == ["/usr/bin/open", "-b", "com.image-line.flstudio", "--", str(path)]
    path.unlink()
    assert bridge.open_daw_project(project["id"])["missing"]
    bridge._window.create_file_dialog.return_value = None
    assert bridge.choose_audio_file(project["id"])["cancelled"]


def legacy_database(path):
    engine = create_engine(f"sqlite:///{path}")
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "musicflow" / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001")
        connection.exec_driver_sql("INSERT INTO projects (id,title,status,notes,archived,created_at,updated_at) VALUES (1,'Старый трек','idea','Старая идея',0,'2026-10-14 12:00:00','2026-10-14 12:00:00')")
        connection.exec_driver_sql("INSERT INTO tasks (id,project_id,title,completed,position) VALUES (1,1,'Написать бит',1,0)")
    engine.dispose()


def test_upgrade_existing_database_and_restore_v01_copy(library):
    client, database, tmp, _ = library
    legacy = tmp / "legacy.sqlite3"
    legacy_database(legacy)
    before = legacy.read_bytes()
    assert Database.validate_backup(legacy) == "0001"
    database.restore(legacy)
    assert legacy.read_bytes() == before
    project = client.get("/api/projects").json()[0]
    assert project["title"] == "Старый трек" and project["notes"] == "Старая идея"
    assert project["tasks"][0]["completed"] and project["preview_auto"]
    assert project["tags"] == [] and project["collections"] == []
    directory = tmp / "old-install"
    directory.mkdir()
    legacy_database(directory / "musicflow.sqlite3")
    upgraded = Database(directory)
    assert list((directory / "backups").glob("*-before-migration.sqlite3"))
    assert Database.validate_backup(upgraded.path) == "0003"
    upgraded.engine.dispose()


def test_new_fields_and_collections_survive_backup_and_restore(library):
    client, database, tmp, _ = library
    collection = client.post("/api/collections", json={"name": "EP"}).json()
    project = client.post("/api/projects", json={"title": "Track", "tags": ["Ночь"], "collection_ids": [collection["id"]], "daw_path": str(tmp / "track.flp"), "preview_path": str(tmp / "demo.wav"), "preview_auto": False}).json()
    destination = tmp / "new.sqlite3"
    database.backup(destination)
    client.delete(f'/api/collections/{collection["id"]}')
    database.restore(destination)
    restored = client.get(f'/api/projects/{project["id"]}').json()
    assert restored["tags"] == ["Ночь"] and restored["collections"][0]["name"] == "EP"
    assert restored["daw_path"] == project["daw_path"] and restored["preview_path"] == project["preview_path"]
