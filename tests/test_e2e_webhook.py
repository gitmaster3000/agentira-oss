"""End-to-end webhook delivery test.

Exercises the full path:
  1. Bootstrap backend with fresh DB
  2. Create a bot profile with webhook_url → live HTTP receiver
  3. Create project, add bot as member
  4. Create task assigned to bot → backend fires task.assigned webhook
  5. Move task → backend fires task.moved webhook
  6. Add comment → backend fires task.commented webhook
  7. Assert the webhook receiver got all three payloads with correct structure

Uses FastAPI TestClient for the REST API and a real stdlib HTTP server
for the webhook receiver (agent_notifier dispatches in background threads
to real URLs, so a live server is required).
"""

from __future__ import annotations

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services
from backend.rest_api import app


# ── Live webhook receiver ─────────────────────────────────────────────────

RECEIVER_PORT = 19300
received_payloads: queue.Queue = queue.Queue()
received_headers: queue.Queue = queue.Queue()


class _WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        payload = json.loads(body)
        received_payloads.put(payload)
        received_headers.put(dict(self.headers))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):
        pass  # suppress access logs


@pytest.fixture(scope="module")
def webhook_server():
    """Start a real HTTP server to receive webhooks."""
    srv = HTTPServer(("127.0.0.1", RECEIVER_PORT), _WebhookHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()


# ── Test DB ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession):
        db = TestSession()
        services._seed_defaults(db)
        db.close()
        yield TestSession


@pytest.fixture()
def api():
    return TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────

def drain_payloads(timeout: float = 2.0) -> list[dict]:
    """Drain all payloads received within the timeout window."""
    results = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            results.append(received_payloads.get(timeout=0.1))
        except queue.Empty:
            if results:
                break  # got at least one, stop waiting
    return results


def drain_headers(timeout: float = 2.0) -> list[dict]:
    """Drain all header dicts received within the timeout window."""
    results = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            results.append(received_headers.get(timeout=0.1))
        except queue.Empty:
            if results:
                break
    return results


# ── E2E test ──────────────────────────────────────────────────────────────

class TestEndToEndWebhook:
    """Full integration: REST API → services → agent_notifier → live HTTP receiver."""

    def test_full_webhook_flow(self, api, webhook_server):
        # ── 1. Create admin + bot profiles ────────────────────────────────
        r = api.post("/api/profiles", json={
            "name": "e2e-admin", "role": "admin"
        })
        assert r.status_code == 200
        admin = r.json()

        r = api.post("/api/profiles", json={
            "name": "e2e-bot", "role": "bot"
        })
        assert r.status_code == 200
        bot = r.json()

        # ── 2. Set webhook_url on bot ─────────────────────────────────────
        r = api.patch(f"/api/profiles/{bot['id']}", json={
            "webhook_url": f"http://127.0.0.1:{RECEIVER_PORT}/webhook"
        })
        assert r.status_code == 200
        assert r.json()["webhook_url"].endswith(f":{RECEIVER_PORT}/webhook")

        # ── 3. Create project + add bot as member ─────────────────────────
        r = api.post("/api/projects", json={
            "name": "E2E Webhook Project", "actor": "e2e-admin"
        })
        assert r.status_code == 200
        project = r.json()

        r = api.post(f"/api/projects/{project['id']}/members", json={
            "profile_name": "e2e-bot", "actor": "e2e-admin"
        })
        assert r.status_code == 200

        # Drain any project-level webhooks (project.member.add)
        member_payloads = drain_payloads(timeout=1.5)

        # ── 4. Create task assigned to bot → task.assigned webhook ────────
        # Clear queue
        while not received_payloads.empty():
            received_payloads.get_nowait()

        r = api.post("/api/tasks", json={
            "project_id": project["id"],
            "title": "Implement feature X",
            "description": "Build the feature",
            "assignee": "e2e-bot",
            "status": "todo",
            "priority": "high",
            "actor": "e2e-admin",
        })
        assert r.status_code == 200
        task = r.json()

        payloads = drain_payloads()
        assigned_events = [p for p in payloads if p.get("event") == "task.assigned"]
        assert len(assigned_events) >= 1, f"Expected task.assigned webhook, got events: {[p.get('event') for p in payloads]}"

        ev = assigned_events[0]
        assert ev["task_id"] == task["id"]
        assert ev["project_id"] == project["id"]
        assert ev["priority"] == "high"
        assert ev["actor"] == "e2e-admin"
        assert "timestamp" in ev
        # Structured only — no freeform 'message' field
        assert "message" not in ev

        # ── 5. Move task → task.moved webhook ─────────────────────────────
        while not received_payloads.empty():
            received_payloads.get_nowait()

        r = api.post(f"/api/tasks/{task['id']}/move", json={
            "status": "in_progress", "actor": "e2e-admin"
        })
        assert r.status_code == 200

        payloads = drain_payloads()
        moved_events = [p for p in payloads if p.get("event") == "task.moved"]
        assert len(moved_events) >= 1, f"Expected task.moved webhook, got: {[p.get('event') for p in payloads]}"
        assert moved_events[0]["task_id"] == task["id"]
        assert moved_events[0]["status"] == "in_progress"

        # ── 6. Add comment → task.commented webhook ───────────────────────
        while not received_payloads.empty():
            received_payloads.get_nowait()

        r = api.post(f"/api/tasks/{task['id']}/comment", json={
            "comment": "Please check the edge cases", "actor": "e2e-admin"
        })
        assert r.status_code == 200

        payloads = drain_payloads()
        comment_events = [p for p in payloads if p.get("event") == "task.commented"]
        assert len(comment_events) >= 1, f"Expected task.commented webhook, got: {[p.get('event') for p in payloads]}"
        assert comment_events[0]["task_id"] == task["id"]
        assert comment_events[0]["actor"] == "e2e-admin"
        # Comment text must NOT be in the payload (prompt injection defense)
        payload_str = json.dumps(comment_events[0])
        assert "edge cases" not in payload_str, "Raw comment text leaked into webhook payload!"

    def test_no_webhook_for_poll_only_bot(self, api, webhook_server):
        """Bot without webhook_url should not receive any webhook POST."""
        admin = api.post("/api/profiles", json={"name": "poll-admin", "role": "admin"}).json()
        bot = api.post("/api/profiles", json={"name": "poll-bot", "role": "bot"}).json()
        # No webhook_url set on poll-bot

        proj = api.post("/api/projects", json={"name": "Poll Project", "actor": "poll-admin"}).json()
        api.post(f"/api/projects/{proj['id']}/members", json={"profile_name": "poll-bot", "actor": "poll-admin"})

        # Drain any stale payloads
        drain_payloads(timeout=0.5)
        while not received_payloads.empty():
            received_payloads.get_nowait()

        # Create task assigned to poll-bot
        api.post("/api/tasks", json={
            "project_id": proj["id"],
            "title": "Poll-only task",
            "assignee": "poll-bot",
            "actor": "poll-admin",
        })

        # Should NOT receive any webhook
        payloads = drain_payloads(timeout=1.0)
        bot_events = [p for p in payloads if p.get("task_id")]
        assert len(bot_events) == 0, f"Poll-only bot should not get webhooks, got: {bot_events}"

    def test_webhook_payload_structure(self, api, webhook_server):
        """Verify the exact payload contract from ADR-007."""
        admin = api.post("/api/profiles", json={"name": "struct-admin", "role": "admin"}).json()
        bot = api.post("/api/profiles", json={"name": "struct-bot", "role": "bot"}).json()
        api.patch(f"/api/profiles/{bot['id']}", json={
            "webhook_url": f"http://127.0.0.1:{RECEIVER_PORT}/webhook"
        })

        proj = api.post("/api/projects", json={"name": "Struct Project", "actor": "struct-admin"}).json()
        api.post(f"/api/projects/{proj['id']}/members", json={"profile_name": "struct-bot", "actor": "struct-admin"})
        drain_payloads(timeout=0.5)
        while not received_payloads.empty():
            received_payloads.get_nowait()

        task = api.post("/api/tasks", json={
            "project_id": proj["id"],
            "title": "Verify contract",
            "assignee": "struct-bot",
            "priority": "critical",
            "actor": "struct-admin",
        }).json()

        payloads = drain_payloads()
        assert len(payloads) >= 1

        ev = payloads[0]
        # All required fields per ADR-007
        required_keys = {"event", "task_id", "task_title", "project_id", "status", "priority", "actor", "timestamp"}
        assert required_keys.issubset(ev.keys()), f"Missing keys: {required_keys - ev.keys()}"

        # No extra freeform fields
        assert "message" not in ev
        assert "description" not in ev
        assert "comment" not in ev

    def test_webhook_sends_auth_token(self, api, webhook_server):
        """Verify Authorization: Bearer header arrives when project has a webhook token."""
        from backend import agent_notifier

        admin = api.post("/api/profiles", json={"name": "auth-admin", "role": "admin"}).json()
        bot = api.post("/api/profiles", json={"name": "auth-bot", "role": "bot"}).json()
        api.patch(f"/api/profiles/{bot['id']}", json={
            "webhook_url": f"http://127.0.0.1:{RECEIVER_PORT}/webhook"
        })

        proj = api.post("/api/projects", json={"name": "Auth Token Project", "actor": "auth-admin"}).json()
        api.post(f"/api/projects/{proj['id']}/members", json={"profile_name": "auth-bot", "actor": "auth-admin"})

        # Set webhook_config with a shared secret token
        services.set_webhook_config(
            proj["id"], enabled=True,
            rules=agent_notifier.DEFAULT_WEBHOOK_RULES,
            token="agentira-shared-secret",
        )

        # Drain any setup webhooks
        drain_payloads(timeout=1.0)
        drain_headers(timeout=0.5)
        while not received_payloads.empty():
            received_payloads.get_nowait()
        while not received_headers.empty():
            received_headers.get_nowait()

        # Create task assigned to bot — triggers webhook with token
        task = api.post("/api/tasks", json={
            "project_id": proj["id"],
            "title": "Auth token test",
            "assignee": "auth-bot",
            "actor": "auth-admin",
        }).json()

        payloads = drain_payloads()
        hdrs = drain_headers()
        assert len(payloads) >= 1, f"Expected webhook delivery, got none"
        assert len(hdrs) >= 1, f"Expected captured headers, got none"
        assert hdrs[0].get("Authorization") == "Bearer agentira-shared-secret"
