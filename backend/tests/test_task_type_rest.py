"""Task type (task | bug) is settable over REST on create and on update."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    _, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    yield c


def _project(client):
    return client.post("/api/projects", json={"name": "P"}).json()["id"]


def test_create_defaults_to_task(client):
    pid = _project(client)
    r = client.post("/api/tasks", json={"project_id": pid, "title": "t"})
    assert r.status_code == 200
    assert r.json()["type"] == "task"


def test_create_bug(client):
    pid = _project(client)
    r = client.post("/api/tasks", json={"project_id": pid, "title": "b", "type": "bug"})
    assert r.status_code == 200
    assert r.json()["type"] == "bug"


def test_update_type_task_to_bug_and_back(client):
    pid = _project(client)
    tid = client.post("/api/tasks", json={"project_id": pid, "title": "t"}).json()["id"]
    r = client.patch(f"/api/tasks/{tid}", json={"type": "bug"})
    assert r.status_code == 200
    assert r.json()["type"] == "bug"
    r = client.patch(f"/api/tasks/{tid}", json={"type": "task"})
    assert r.json()["type"] == "task"


def test_update_unknown_type_rejected(client):
    pid = _project(client)
    tid = client.post("/api/tasks", json={"project_id": pid, "title": "t"}).json()["id"]
    r = client.patch(f"/api/tasks/{tid}", json={"type": "epic"})
    assert r.status_code == 400
