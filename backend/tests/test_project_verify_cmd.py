"""Loop v1 C6: `verify_cmd` — the command that proves the project works,
run by the daemon on the merged code before anything is pushed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    _, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_verify_cmd_round_trips(client):
    pid = client.post("/api/projects", json={"name": "V"}).json()["id"]
    r = client.patch(f"/api/projects/{pid}",
                     json={"verify_cmd": "  scripts/verify.sh ",
                           "verify_timeout_minutes": 20})
    assert r.status_code == 200
    got = client.get(f"/api/projects/{pid}").json()
    assert got["verify_cmd"] == "scripts/verify.sh"
    assert got["verify_timeout_minutes"] == 20


def test_verify_cmd_can_be_cleared(client):
    pid = client.post("/api/projects", json={"name": "V2"}).json()["id"]
    client.patch(f"/api/projects/{pid}", json={"verify_cmd": "make test"})
    client.patch(f"/api/projects/{pid}", json={"verify_cmd": ""})
    assert client.get(f"/api/projects/{pid}").json()["verify_cmd"] == ""


def test_verify_timeout_is_clamped(client):
    pid = client.post("/api/projects", json={"name": "V3"}).json()["id"]
    client.patch(f"/api/projects/{pid}", json={"verify_timeout_minutes": 100000})
    assert client.get(f"/api/projects/{pid}").json()["verify_timeout_minutes"] == 240
    client.patch(f"/api/projects/{pid}", json={"verify_timeout_minutes": 0})
    assert client.get(f"/api/projects/{pid}").json()["verify_timeout_minutes"] == 1
