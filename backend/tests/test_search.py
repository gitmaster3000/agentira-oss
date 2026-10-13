"""Global search endpoint: matches across entities, scoped to accessible projects."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    admin_id, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    yield c


def test_search_finds_task_and_project(client):
    pid = client.post("/api/projects", json={"name": "Zebra Platform"}).json()["id"]
    client.post("/api/tasks", json={"project_id": pid, "title": "Fix quokka login loop"})
    r = client.get("/api/search", params={"q": "quokka"})
    assert r.status_code == 200
    body = r.json()
    assert [t["title"] for t in body["tasks"]] == ["Fix quokka login loop"]
    assert body["tasks"][0]["project_name"] == "Zebra Platform"
    assert client.get("/api/search", params={"q": "zebra"}).json()["projects"][0]["id"] == pid


def test_search_empty_and_no_match(client):
    assert client.get("/api/search", params={"q": ""}).json() == {
        "projects": [], "tasks": [], "epics": [], "agents": []}
    assert client.get("/api/search", params={"q": "nothing-matches-xyz"}).json()["tasks"] == []


def test_search_wildcards_are_literal(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    client.post("/api/tasks", json={"project_id": pid, "title": "plain title"})
    assert client.get("/api/search", params={"q": "%"}).json()["tasks"] == []


def test_search_requires_auth():
    assert TestClient(app).get("/api/search", params={"q": "x"}).status_code in (401, 403)


def test_search_hides_projects_user_is_not_member_of(client, pg):
    from backend.models import Profile, Role
    from backend.jwt_auth import create_token
    from backend.db import SessionLocal
    pid = client.post("/api/projects", json={"name": "Secret Vault"}).json()["id"]
    client.post("/api/tasks", json={"project_id": pid, "title": "hidden quokka"})
    with SessionLocal() as db:
        role = db.query(Role).filter(Role.name == "member").first()
        u = Profile(name="outsider", account_type="human", roles=[role], password_hash="")
        db.add(u)
        db.commit()
        uid = u.id
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {create_token('outsider', uid, ['member'], org_id=pg.org_id)}"
    body = c.get("/api/search", params={"q": "quokka"}).json()
    assert body["tasks"] == [] and body["projects"] == []
    assert c.get("/api/search", params={"q": "vault"}).json()["projects"] == []
