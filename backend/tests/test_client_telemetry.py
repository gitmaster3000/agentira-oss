import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import client_telemetry


@pytest.fixture
def client():
    client_telemetry._hits.clear()
    app = FastAPI()
    app.include_router(client_telemetry.router)
    return TestClient(app)


@pytest.fixture
def lines(caplog):
    logger = logging.getLogger("agentira.client")
    logger.propagate = True
    caplog.set_level(logging.DEBUG, logger="agentira.client")
    yield lambda: [(r.levelname, json.loads(r.getMessage())) for r in caplog.records
                   if r.name == "agentira.client"]
    logger.propagate = False


def test_logs_one_json_line_per_event_with_context(client, lines):
    r = client.post("/api/client-logs", json={
        "session": "s1", "release": "abc123", "tz": "Asia/Dubai",
        "events": [
            {"kind": "interaction", "event": "keydown", "duration": 480,
             "target": "textarea[Add a comment]", "route": "/studio/tasks/:id"},
            {"kind": "error", "message": "boom", "error_id": "e1", "route": "/studio"},
        ],
    })
    assert r.status_code == 200
    assert r.json() == {"level": "info"}  # anonymous: never debug
    out = lines()
    assert [lvl for lvl, _ in out] == ["WARNING", "ERROR"]
    first = out[0][1]
    assert first["kind"] == "interaction" and first["duration"] == 480
    assert first["tz"] == "Asia/Dubai" and first["session"] == "s1"


def test_drops_unknown_kinds_and_fields(client, lines):
    client.post("/api/client-logs", json={"events": [
        {"kind": "api", "endpoint": "/tasks", "duration": 900, "password": "x"},
        {"kind": "nonsense", "x": 1},
    ]})
    out = lines()
    assert len(out) == 1
    assert "password" not in out[0][1]


def test_rejects_oversized_and_malformed(client):
    assert client.post("/api/client-logs", content=b"x" * (70 * 1024)).status_code == 413
    assert client.post("/api/client-logs", content=b"not json").status_code == 400
    assert client.post("/api/client-logs", json={"events": "nope"}).status_code == 400


def test_rate_limited_per_ip(client):
    for _ in range(client_telemetry.RATE_PER_MIN):
        assert client.post("/api/client-logs", json={"events": []}).status_code == 200
    assert client.post("/api/client-logs", json={"events": []}).status_code == 429


def test_caps_strings(client, lines):
    client.post("/api/client-logs", json={"events": [
        {"kind": "error", "message": "m" * 5000},
    ]})
    assert len(lines()[0][1]["message"]) == client_telemetry._STR_MAX


# ── Levels: admin commands + automatic switch-on (real app, Postgres) ─────

@pytest.fixture
def api(seed_admin, pg):
    from backend.rest_api import app
    from backend.jwt_auth import create_token
    client_telemetry._hits.clear()
    _, admin_token = seed_admin
    c = TestClient(app)
    c.admin = {"Authorization": f"Bearer {admin_token}"}
    c.member = {"Authorization": "Bearer " + create_token("babar", "p_babar", ["member"], org_id=pg.org_id)}
    return c


def test_admin_switches_user_to_debug_and_back(api):
    assert api.get("/api/client-logs/config", headers=api.member).json()["level"] == "info"
    r = api.post("/api/client-logs/debug", json={"user": "babar", "minutes": 30, "reason": "typing lag"},
                 headers=api.admin)
    assert r.status_code == 200 and r.json()["by"] == "admin"
    assert api.get("/api/client-logs/config", headers=api.member).json()["level"] == "debug"
    assert [d["user"] for d in api.get("/api/client-logs/debug", headers=api.admin).json()] == ["babar"]
    # The browser also learns its level from its own log POST.
    assert api.post("/api/client-logs", json={"events": []}, headers=api.member).json()["level"] == "debug"
    api.delete("/api/client-logs/debug/babar", headers=api.admin)
    assert api.get("/api/client-logs/config", headers=api.member).json()["level"] == "info"


def test_non_admin_cannot_switch(api):
    r = api.post("/api/client-logs/debug", json={"user": "babar"}, headers=api.member)
    assert r.status_code == 403


def test_trouble_switches_user_on_automatically(api):
    calm = {"events": [{"kind": "interaction", "event": "keydown", "duration": 300}]}
    assert api.post("/api/client-logs", json=calm, headers=api.member).json()["level"] == "info"
    slow = {"events": [{"kind": "interaction", "event": "keydown", "duration": 1400}]}
    out = api.post("/api/client-logs", json=slow, headers=api.member).json()
    assert out["level"] == "debug" and "until" in out
    reasons = [d["reason"] for d in api.get("/api/client-logs/debug", headers=api.admin).json()]
    assert reasons == ["auto: slow interaction 1400ms"]


def test_debug_session_api_lines_log_at_debug(client, lines):
    client.post("/api/client-logs", json={"level": "debug", "events": [
        {"kind": "api", "endpoint": "/tasks", "duration": 40, "status": 200, "ok": True},
    ]})
    client.post("/api/client-logs", json={"level": "info", "events": [
        {"kind": "api", "endpoint": "/tasks", "duration": 4000, "status": 200, "ok": True},
    ]})
    assert [lvl for lvl, _ in lines()] == ["DEBUG", "INFO"]
