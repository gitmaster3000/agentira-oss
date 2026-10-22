"""Daemon-side MCP probe: runs on the host, so it sees what agents see."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from agentira_cli.daemon import mcp_probe


def _probe_with(handler, **kw):
    real = httpx.Client
    with patch.object(mcp_probe.httpx, "Client",
                      lambda **k: real(transport=httpx.MockTransport(handler), **k)):
        return mcp_probe.probe_tools("https://x.test/mcp", **kw)


def _rpc(result, sse=False):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})
    if sse:
        return httpx.Response(200, text=f"event: message\ndata: {body}\n\n",
                              headers={"content-type": "text/event-stream"})
    return httpx.Response(200, json=json.loads(body))


@pytest.mark.parametrize("sse", [False, True])
def test_probe_lists_tools(sse):
    seen = []

    def handler(req):
        method = json.loads(req.content)["method"]
        seen.append((method, req.headers.get("authorization")))
        if method == "tools/list":
            return _rpc({"tools": [
                {"name": "get_doc", "description": "Read a doc",
                 "annotations": {"readOnlyHint": True}},
                {"name": "update_node"}]}, sse)
        return _rpc({}, sse) if method == "initialize" else httpx.Response(202)

    out = _probe_with(handler, bearer="tok")
    assert out == {"ok": True, "tools": [
        {"name": "get_doc", "description": "Read a doc", "read_only": True},
        {"name": "update_node", "description": "", "read_only": False}]}
    assert [m for m, _ in seen] == ["initialize", "notifications/initialized", "tools/list"]
    assert all(a == "Bearer tok" for _, a in seen)


def test_probe_reports_rejected_credentials_in_plain_words():
    out = _probe_with(lambda req: httpx.Response(401))
    assert out["ok"] is False and "rejected the credentials" in out["error"]


def test_probe_reports_unreachable_server():
    def boom(req):
        raise httpx.ConnectError("nope")

    out = _probe_with(boom)
    assert out["ok"] is False and "Could not reach" in out["error"]


# ── frame handler ────────────────────────────────────────────────────────

def test_run_frame_probes_each_registered_server_by_name():
    calls = []

    def fake(url, bearer=None, **kw):
        calls.append((url, bearer))
        return {"ok": True, "tools": []}

    frame = {"request_id": "r1", "servers": [
        {"name": "ezine", "url": "http://localhost:4400/mcp", "bearer": "k"}]}
    with patch.object(mcp_probe, "probe_tools", fake):
        out = mcp_probe.run_frame(frame, claude_json={})
    assert calls == [("http://localhost:4400/mcp", "k")]
    assert out == {"type": "reply", "request_id": "r1",
                   "servers": {"ezine": {"ok": True, "tools": []}}, "host": []}


def test_run_frame_includes_host_servers_with_their_own_headers():
    cfg = {"mcpServers": {
        "ezine": {"type": "http", "url": "https://ezine.up.railway.app/mcp",
                  "headers": {"Authorization": "Bearer hostsecret"}},
        "mem": {"command": "npx", "args": ["x"]}}}
    seen = {}

    def fake(url, bearer=None, **kw):
        seen[url] = bearer
        return {"ok": True, "tools": [{"name": "t", "description": "", "read_only": False}]}

    with patch.object(mcp_probe, "probe_tools", fake):
        out = mcp_probe.run_frame({"request_id": "r", "servers": [], "host": True},
                                  claude_json=cfg)
    assert seen == {"https://ezine.up.railway.app/mcp": "hostsecret"}
    by = {h["name"]: h for h in out["host"]}
    assert by["ezine"]["ok"] is True and by["ezine"]["transport"] == "http"
    assert by["mem"] == {"name": "mem", "transport": "stdio", "url": "", "command": "npx",
                         "ok": None, "tools": [], "error": ""}
    assert "hostsecret" not in json.dumps(out)


# ── WS wiring ────────────────────────────────────────────────────────────

def test_ws_client_answers_probe_frame_over_the_socket():
    import queue
    import threading

    from agentira_cli.daemon.ws_client import DaemonWsClient

    sent = []

    class FakeWs:
        def send(self, raw):
            sent.append(json.loads(raw))

    c = DaemonWsClient("http://x", "k", "d1", [], threading.Event(), queue.Queue())
    with patch.object(mcp_probe, "run_frame",
                      lambda f: {"type": "reply", "request_id": f["request_id"],
                                 "servers": {}, "host": []}):
        c._answer_probe(FakeWs(), {"type": "mcp_probe", "request_id": "r9", "servers": []})
    assert sent == [{"type": "reply", "request_id": "r9", "servers": {}, "host": []}]
