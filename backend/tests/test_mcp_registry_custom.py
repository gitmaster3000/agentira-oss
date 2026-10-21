"""Org-registered MCP servers: config merge, tool allow-lists, probe, REST."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.forge import mcp_probe
from backend.forge.mcp_registry import build_mcp_config
from backend.rest_api import app

EZINE = {"transport": "http", "url": "https://ezine.test/mcp", "auth_mode": "agent_key",
         "token": None, "tool_names": ["get_prototype", "list_docs", "update_node"]}


def _cfg(**kw):
    kw.setdefault("agent_id", "a1")
    kw.setdefault("project_id", None)
    kw.setdefault("custom_servers", {"ezine": EZINE})
    return build_mcp_config(**{"agent_mcp_servers": ["ezine"], **kw})


# ── build_mcp_config ─────────────────────────────────────────────────────

def test_custom_server_is_opt_in():
    assert "ezine" not in _cfg(agent_mcp_servers=[])["mcpServers"]
    assert "ezine" in _cfg()["mcpServers"]


def test_agent_key_auth_uses_the_agents_own_key():
    entry = _cfg(agent_api_key="agent-key")["mcpServers"]["ezine"]
    assert entry == {"type": "http", "url": "https://ezine.test/mcp",
                     "headers": {"Authorization": "Bearer agent-key"}}


def test_bearer_auth_uses_stored_token():
    srv = {**EZINE, "auth_mode": "bearer", "token": "s3cret"}
    entry = _cfg(custom_servers={"ezine": srv}, agent_api_key="agent-key")["mcpServers"]["ezine"]
    assert entry["headers"] == {"Authorization": "Bearer s3cret"}


def test_no_auth_sends_no_header():
    srv = {**EZINE, "auth_mode": "none"}
    assert "headers" not in _cfg(custom_servers={"ezine": srv}, agent_api_key="k")["mcpServers"]["ezine"]


def test_builtin_name_beats_custom_server():
    clash = {**EZINE, "url": "https://evil.test/mcp"}
    cfg = build_mcp_config(agent_mcp_servers=["memory"], agent_id="a", project_id=None,
                           custom_servers={"memory": clash})
    assert cfg["mcpServers"]["memory"]["command"] == "npx"


def test_tool_allow_list_denies_the_rest():
    cfg = _cfg(tool_allow={"ezine": ["get_prototype", "list_docs"]})
    assert cfg["agentiraDisallowedTools"] == ["mcp__ezine__update_node"]


def test_tool_allow_accepts_json_string_and_ignores_unlisted_servers():
    cfg = _cfg(tool_allow=json.dumps({"ezine": ["list_docs"], "other": ["x"]}))
    assert set(cfg["agentiraDisallowedTools"]) == {
        "mcp__ezine__get_prototype", "mcp__ezine__update_node"}


def test_no_allow_list_means_all_tools_and_no_key():
    assert "agentiraDisallowedTools" not in _cfg()
    assert "agentiraDisallowedTools" not in _cfg(tool_allow="not json")


# ── probe ────────────────────────────────────────────────────────────────

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


# ── REST ─────────────────────────────────────────────────────────────────

TOOLS = [{"name": "get_prototype", "description": "", "read_only": True},
         {"name": "update_node", "description": "", "read_only": False}]


@pytest.fixture
def client(seed_admin):
    _, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    yield c


@pytest.fixture
def probe_ok():
    with patch("backend.forge.mcp_servers.probe_tools",
               return_value={"ok": True, "tools": TOOLS}) as p:
        yield p


def test_add_server_probes_and_returns_tools_without_secret(client, probe_ok):
    r = client.post("/api/forge/mcp-registry", json={
        "name": "ezine", "url": "https://ezine.test/mcp",
        "auth_mode": "bearer", "token": "s3cret"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "ok" and [t["name"] for t in body["tools"]] == [
        "get_prototype", "update_node"]
    assert body["has_token"] is True and "s3cret" not in r.text
    probe_ok.assert_called_once_with("https://ezine.test/mcp", "s3cret")


def test_agent_key_probe_uses_callers_token(client, probe_ok):
    client.post("/api/forge/mcp-registry", json={
        "name": "ezine", "url": "https://ezine.test/mcp", "auth_mode": "agent_key"})
    sent = probe_ok.call_args.args[1]
    assert sent == client.headers["Authorization"].removeprefix("Bearer ")


def test_token_is_encrypted_at_rest(client, probe_ok, pg):
    from backend.models import McpServer
    client.post("/api/forge/mcp-registry", json={
        "name": "ezine", "url": "https://ezine.test/mcp",
        "auth_mode": "bearer", "token": "s3cret"})
    with pg.SessionLocal() as db:
        assert db.query(McpServer).one().token != "s3cret"


@pytest.mark.parametrize("payload,fragment", [
    ({"name": "memory", "url": "https://x.test"}, "built-in"),
    ({"name": "Bad Name!", "url": "https://x.test"}, "Name must be"),
    ({"name": "ok", "url": "ftp://x.test"}, "URL must start"),
    ({"name": "ok", "url": "https://x.test", "auth_mode": "magic"}, "auth_mode"),
])
def test_add_server_validation(client, probe_ok, payload, fragment):
    r = client.post("/api/forge/mcp-registry", json=payload)
    assert r.status_code == 400 and fragment in r.json()["detail"]


def test_duplicate_name_rejected(client, probe_ok):
    body = {"name": "ezine", "url": "https://ezine.test/mcp"}
    assert client.post("/api/forge/mcp-registry", json=body).status_code == 201
    assert client.post("/api/forge/mcp-registry", json=body).status_code == 400


def test_failed_probe_is_saved_as_error_status(client):
    with patch("backend.forge.mcp_servers.probe_tools",
               return_value={"ok": False, "error": "Could not reach the server."}):
        r = client.post("/api/forge/mcp-registry", json={
            "name": "ezine", "url": "https://ezine.test/mcp"})
    assert r.status_code == 201
    assert r.json()["status"] == "error" and "Could not reach" in r.json()["status_detail"]


def test_picker_lists_enabled_servers_with_tools_and_disable_hides_them(client, probe_ok):
    sid = client.post("/api/forge/mcp-registry", json={
        "name": "ezine", "url": "https://ezine.test/mcp"}).json()["id"]
    picker = {s["name"]: s for s in client.get("/api/forge/mcp-servers").json()}
    assert picker["ezine"]["custom"] is True and len(picker["ezine"]["tools"]) == 2
    client.patch(f"/api/forge/mcp-registry/{sid}", json={"enabled": False})
    assert "ezine" not in {s["name"] for s in client.get("/api/forge/mcp-servers").json()}


def test_patch_without_token_keeps_stored_token(client, probe_ok, pg):
    from backend.forge.repos import mcp_servers as repo
    sid = client.post("/api/forge/mcp-registry", json={
        "name": "ezine", "url": "https://ezine.test/mcp",
        "auth_mode": "bearer", "token": "s3cret"}).json()["id"]
    client.patch(f"/api/forge/mcp-registry/{sid}", json={"description": "Design tool"})
    with pg.SessionLocal() as db:
        assert repo.token_of(repo.get(db, sid)) == "s3cret"


def test_test_endpoint_refreshes_tools_and_delete_removes(client, probe_ok):
    sid = client.post("/api/forge/mcp-registry", json={
        "name": "ezine", "url": "https://ezine.test/mcp"}).json()["id"]
    probe_ok.return_value = {"ok": True, "tools": TOOLS[:1]}
    assert len(client.post(f"/api/forge/mcp-registry/{sid}/test").json()["tools"]) == 1
    assert client.delete(f"/api/forge/mcp-registry/{sid}").status_code == 200
    assert client.get("/api/forge/mcp-registry").json() == []
    assert client.post(f"/api/forge/mcp-registry/{sid}/test").status_code == 404


def test_registry_endpoints_are_admin_only(pg):
    assert TestClient(app).get("/api/forge/mcp-registry").status_code in (401, 403)


def test_dispatch_config_includes_registered_server(client, probe_ok):
    client.post("/api/forge/mcp-registry", json={
        "name": "ezine", "url": "https://ezine.test/mcp", "auth_mode": "agent_key"})
    cfg = build_mcp_config(agent_mcp_servers=["ezine"], agent_id="a", project_id=None,
                           agent_api_key="agent-key",
                           tool_allow={"ezine": ["get_prototype"]})
    assert cfg["mcpServers"]["ezine"]["headers"] == {"Authorization": "Bearer agent-key"}
    assert cfg["agentiraDisallowedTools"] == ["mcp__ezine__update_node"]
