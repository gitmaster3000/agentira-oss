"""AP-121: REST surface for project_repos.

The MCP tool already exists; this is the thin HTTP layer the browser
UI needs (browser → REST, agents → MCP).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
import backend.forge.models  # noqa: F401 — FK target registration
from backend.rest_api import app
from backend.jwt_auth import create_token


@pytest.fixture
def client():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.db.SessionLocal", TestSession), \
         patch("backend.rest_api.services._session",
               lambda: TestSession()):
        db = TestSession()
        core_services._seed_defaults(db)
        # Admin profile so JWT decode resolves the actor.
        from backend.models import Profile, Role
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        admin = Profile(name="admin", role_id=admin_role.id, password_hash="")
        db.add(admin)
        db.commit()
        token = create_token("admin", admin.id, "admin", admin.org_id)
        db.close()
        c = TestClient(app)
        c.headers["Authorization"] = f"Bearer {token}"
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
