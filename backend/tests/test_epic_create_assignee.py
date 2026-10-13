"""Epic create accepts an assignee (create dialog shares fields across types)."""

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


def test_create_epic_with_assignee(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/epics", json={"title": "E", "assignee": "alice"})
    assert r.status_code == 200
    assert r.json()["assignee"] == "alice"


def test_create_epic_assignee_defaults_empty(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/epics", json={"title": "E"})
    assert r.json()["assignee"] == ""
