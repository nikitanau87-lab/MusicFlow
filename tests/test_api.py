from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from musicflow.api import create_app
from musicflow.database import Database


@pytest.fixture
def setup(tmp_path):
    database = Database(tmp_path / "data")
    with TestClient(create_app(database, "test-token"), headers={"X-MusicFlow-Token": "test-token"}) as client:
        yield client, database
    database.engine.dispose()


def add(client, **fields):
    response = client.post("/api/projects", json={"title": "Ночной трек", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def test_token_required(setup):
    client, _ = setup
    assert client.get("/api/projects", headers={"X-MusicFlow-Token": ""}).status_code == 403
    assert client.post("/api/projects", headers={"X-MusicFlow-Token": "wrong"}, json={"title": "no"}).status_code == 403
    assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize("fields", [{"title": "  "}, {"title": None}, {"bpm": 0}, {"bpm": -1}, {"status": "invalid"}, {"folder_path": "relative/path"}, {"unexpected": True}])
def test_validation(setup, fields):
    client, _ = setup
    assert client.post("/api/projects", json={"title": "Track", **fields}).status_code == 422
    assert client.get("/api/projects").json() == []


def test_project_lifecycle_and_persistence(setup):
    client, database = setup
    project = add(client, bpm=127.5, genre="House", musical_key="A minor", folder_path="/tmp/Музыка с пробелами", notes="Референс")
    assert project["tasks"] == [] and project["progress"] is None
    updated = client.patch(f'/api/projects/{project["id"]}', json={"title": "Новое название", "status": "mixing"}).json()
    assert updated["bpm"] == 127.5
    assert updated["created_at"] == project["created_at"]
    assert client.patch(f'/api/projects/{project["id"]}', json={"title": None}).status_code == 422
    client.patch(f'/api/projects/{project["id"]}', json={"archived": True})
    assert client.get("/api/projects").json() == []
    assert client.get("/api/projects?archived=true").json()[0]["id"] == project["id"]
    client.patch(f'/api/projects/{project["id"]}', json={"archived": False})
    reopened = Database(database.directory)
    with TestClient(create_app(reopened, "test-token"), headers={"X-MusicFlow-Token": "test-token"}) as other:
        assert other.get(f'/api/projects/{project["id"]}').json()["title"] == "Новое название"
    reopened.engine.dispose()
    client.delete(f'/api/projects/{project["id"]}')
    assert client.get(f'/api/projects/{project["id"]}').status_code == 404


def test_search_filters_sorting_cyrillic(setup):
    client, _ = setup
    first = add(client, title="Яркий ТРЕК", status="working", genre="House")
    add(client, title="Атмосфера", genre="Ambient")
    add(client, title="Архив", status="done")
    result = client.get("/api/projects?search=яркий&status=working&genre=House").json()
    assert [p["id"] for p in result] == [first["id"]]
    assert [p["title"] for p in client.get("/api/projects?sort=title").json()] == ["Архив", "Атмосфера", "Яркий ТРЕК"]
    assert client.get("/api/projects?search=неизвестный").json() == []
    assert client.get("/api/overview").json() == {"active": 3, "archived": 0, "done": 1, "genres": ["Ambient", "House"], "tags": []}


def test_tasks_template_progress_order_isolation_cascade(setup):
    client, _ = setup
    project = add(client)
    other = add(client, title="Другой")
    base = f'/api/projects/{project["id"]}/tasks'
    response = client.post(base + "/template").json()
    assert len(response["tasks"]) == 4
    assert len(client.post(base + "/template").json()["tasks"]) == 4
    ids = [task["id"] for task in response["tasks"]]
    updated = client.patch(f"{base}/{ids[0]}", json={"completed": True}).json()
    assert updated["progress"] == 25 and updated["status"] == "idea"
    client.patch(f"{base}/{ids[0]}", json={"title": "Новый бит"})
    assert client.patch(f'/api/projects/{other["id"]}/tasks/{ids[0]}', json={"completed": True}).status_code == 404
    assert client.put(base + "/order", json={"ids": [ids[0]] * 4}).status_code == 422
    ordered = client.put(base + "/order", json={"ids": list(reversed(ids))}).json()
    assert [task["id"] for task in ordered["tasks"]] == list(reversed(ids))
    deleted = client.delete(f"{base}/{ids[2]}").json()
    assert [task["position"] for task in deleted["tasks"]] == [0, 1, 2]
    assert client.post(base, json={"title": ""}).status_code == 422
    client.delete(f'/api/projects/{project["id"]}')
    with setup[1].engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM tasks").scalar() == 0


def test_concurrent_requests_do_not_cross_thread_unlock(setup):
    client, _ = setup
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda i: client.post("/api/projects", json={"title": f"Track {i}"}), range(12)))
    assert all(response.status_code == 201 for response in responses)
    assert len(client.get("/api/projects").json()) == 12
