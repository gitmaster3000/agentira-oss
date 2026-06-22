"""AP-121: REST surface for project_repos.

The MCP tool already exists; this is the thin HTTP layer the browser
UI needs (browser → REST, agents → MCP).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import services as core_services
import backend.forge.models  # noqa: F401 — FK target registration
from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    admin_id, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    c.admin_id = admin_id
    yield c


def _make_project(client, name="P"):
    res = client.post("/api/projects", json={"name": name, "description": ""})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_list_repos_empty_by_default(client):
    pid = _make_project(client)
    res = client.get(f"/api/projects/{pid}/repos")
    assert res.status_code == 200
    assert res.json() == []


def test_add_repo_returns_dict(client):
    pid = _make_project(client)
    res = client.post(f"/api/projects/{pid}/repos", json={
        "name": "backend", "repo_path": "/tmp/backend",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "backend"
    assert body["is_primary"] is True  # first repo on the project


def test_add_repo_duplicate_returns_400(client):
    pid = _make_project(client)
    client.post(f"/api/projects/{pid}/repos",
                json={"name": "x", "repo_path": "/a"})
    res = client.post(f"/api/projects/{pid}/repos",
                      json={"name": "x", "repo_path": "/b"})
    assert res.status_code == 400


def test_list_returns_added_repos(client):
    pid = _make_project(client)
    client.post(f"/api/projects/{pid}/repos",
                json={"name": "a", "repo_path": "/a"})
    client.post(f"/api/projects/{pid}/repos",
                json={"name": "b", "repo_path": "/b"})
    res = client.get(f"/api/projects/{pid}/repos")
    names = [r["name"] for r in res.json()]
    assert set(names) == {"a", "b"}


def test_remove_repo(client):
    pid = _make_project(client)
    client.post(f"/api/projects/{pid}/repos",
                json={"name": "x", "repo_path": "/a"})
    res = client.delete(f"/api/projects/{pid}/repos/x")
    assert res.status_code == 200
    assert client.get(f"/api/projects/{pid}/repos").json() == []


def test_remove_unknown_repo_returns_404(client):
    pid = _make_project(client)
    res = client.delete(f"/api/projects/{pid}/repos/ghost")
    assert res.status_code == 404
