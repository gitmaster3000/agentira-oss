"""MCP status is probed by the daemon on the user's machine, not by the backend
container — so a URL only the container can resolve reads as broken."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.forge import daemon_probe
from backend.forge.ws_dispatch import DaemonConnection, WsHub
from backend.rest_api import app


class FakeWs:
    async def send_json(self, _msg):  # pragma: no cover - pump not started
        pass


def _hub_with_daemon(org_id="org1"):
    hub = WsHub()
    conn = DaemonConnection(FakeWs(), "d1", [], org_id=org_id)
    sent = []

    async def send(event_id, payload):
        sent.append(payload)
    conn.send = send
    return hub, conn, sent


def test_request_returns_none_when_no_daemon_online():
    hub = WsHub()
    assert asyncio.run(hub.request({"type": "mcp_probe"}, org_id="org1", timeout=0.1)) is None


def test_request_sends_frame_and_resolves_with_daemon_reply():
    async def go():
        hub, conn, sent = _hub_with_daemon()
        await hub.connect(conn)
        task = asyncio.create_task(hub.request({"type": "mcp_probe", "servers": []},
                                               org_id="org1", timeout=2))
        await asyncio.sleep(0.05)
        rid = sent[0]["request_id"]
        hub.resolve({"type": "reply", "request_id": rid, "servers": {}, "host": []})
        return sent, await task

    sent, reply = asyncio.run(go())
    assert sent[0]["type"] == "mcp_probe"
    assert reply["host"] == []


def test_request_times_out_to_none_when_daemon_never_answers():
    async def go():
        hub, conn, _ = _hub_with_daemon()
        await hub.connect(conn)
        return await hub.request({"type": "mcp_probe"}, org_id="org1", timeout=0.1)

    assert asyncio.run(go()) is None


def test_request_never_uses_another_orgs_daemon():
    async def go():
        hub, conn, sent = _hub_with_daemon(org_id="other")
        await hub.connect(conn)
        return await hub.request({"type": "mcp_probe"}, org_id="org1", timeout=0.1), sent

    reply, sent = asyncio.run(go())
    assert reply is None and sent == []


# ── daemon_probe ─────────────────────────────────────────────────────────

def test_probe_tools_reports_missing_daemon_in_plain_words():
    with patch.object(daemon_probe, "_ask_daemon", return_value=None):
        out = daemon_probe.probe_tools("http://x/mcp", "tok")
    assert out["ok"] is False and "daemon" in out["error"].lower()


def test_probe_tools_returns_the_daemons_verdict():
    reply = {"servers": {"s": {"ok": False, "error": "Could not reach the server."}}}
    with patch.object(daemon_probe, "_ask_daemon", return_value=reply) as ask:
        out = daemon_probe.probe_tools("http://host.docker.internal:4400/mcp", "tok")
    assert out == {"ok": False, "error": "Could not reach the server."}
    frame = ask.call_args.args[0]
    assert frame["servers"] == [{"name": "s", "url": "http://host.docker.internal:4400/mcp",
                                 "bearer": "tok"}]


def test_host_servers_empty_and_unchecked_without_daemon():
    with patch.object(daemon_probe, "_ask_daemon", return_value=None):
        assert daemon_probe.host_servers() == {"checked": False, "servers": []}


# ── REST ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client(seed_admin):
    _, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    yield c


def test_host_endpoint_lists_daemon_reported_servers(client):
    host = [{"name": "ezine", "transport": "http", "url": "https://e/mcp", "command": "",
             "ok": True, "tools": [], "error": ""}]
    with patch.object(daemon_probe, "_ask_daemon", return_value={"servers": {}, "host": host}):
        r = client.get("/api/forge/mcp-registry/host")
    assert r.status_code == 200 and r.json() == {"checked": True, "servers": host}
