"""MCP OAuth: register → consent → code+PKCE → token → refresh, plus scopes."""

from __future__ import annotations

import base64
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from backend import mcp_oauth, mcp_server
from backend.db import privileged, SessionLocal
from backend.models import McpOAuthToken
from backend.rest_api import app as rest_app

REDIRECT = "http://localhost:53682/callback"
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


@pytest.fixture
def rest(seed_admin):
    admin_id, token = seed_admin
    c = TestClient(rest_app)
    c.headers["Authorization"] = f"Bearer {token}"
    c.admin_id = admin_id
    return c


@pytest.fixture
def mcp(pg, monkeypatch):
    # The real session manager can only run once per process; stub it so we
    # test the auth/scope layer in front of it.
    async def ok(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})
    monkeypatch.setattr(mcp_server.session_manager, "handle_request", ok)
    return TestClient(mcp_server.app)


def _register(mcp):
    r = mcp.post("/register", json={"client_name": "Claude", "redirect_uris": [REDIRECT]})
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def _consent(rest, client_id, scope="agentira:read agentira:write", **over):
    body = {"approve": True, "client_id": client_id, "redirect_uri": REDIRECT,
            "code_challenge": CHALLENGE, "code_challenge_method": "S256",
            "scope": scope, "state": "xyz", **over}
    return rest.post("/api/auth/mcp/authorize", json=body)


def _code(rest, client_id, **kw):
    r = _consent(rest, client_id, **kw)
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["redirect_url"]).query)
    assert q["state"] == ["xyz"]
    return q["code"][0]


def _tokens(mcp, client_id, code):
    return mcp.post("/token", data={
        "grant_type": "authorization_code", "client_id": client_id, "code": code,
        "redirect_uri": REDIRECT, "code_verifier": VERIFIER})


def test_discovery_and_401_challenge(mcp):
    r = mcp.post("/mcp", json={})
    assert r.status_code == 401
    assert "oauth-protected-resource" in r.headers["www-authenticate"]
    meta = mcp.get("/.well-known/oauth-authorization-server").json()
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["token_endpoint"].endswith("/token")
    assert mcp.get("/.well-known/oauth-protected-resource").json()["resource"].endswith("/mcp")


def test_register_rejects_plain_http_redirect(mcp):
    r = mcp.post("/register", json={"redirect_uris": ["http://evil.example/cb"]})
    assert r.status_code == 400


def test_full_flow_and_refresh_rotation(mcp, rest):
    cid = _register(mcp)
    t = _tokens(mcp, cid, _code(rest, cid))
    assert t.status_code == 200, t.text
    tok = t.json()
    assert tok["expires_in"] == 3600

    # access token authenticates on /mcp (no 401)
    auth = {"Authorization": f"Bearer {tok['access_token']}"}
    r = mcp.post("/mcp", headers=auth, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 200

    # refresh → new pair; old refresh token is now dead and reuse revokes the grant
    r2 = mcp.post("/token", data={"grant_type": "refresh_token", "client_id": cid,
                                  "refresh_token": tok["refresh_token"]})
    assert r2.status_code == 200, r2.text
    new = r2.json()
    assert new["refresh_token"] != tok["refresh_token"]
    replay = mcp.post("/token", data={"grant_type": "refresh_token", "client_id": cid,
                                      "refresh_token": tok["refresh_token"]})
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
    assert mcp_oauth.validate_access_token(new["access_token"]) is None


def test_code_is_single_use_and_needs_pkce(mcp, rest):
    cid = _register(mcp)
    code = _code(rest, cid)
    bad = mcp.post("/token", data={"grant_type": "authorization_code", "client_id": cid,
                                   "code": code, "redirect_uri": REDIRECT,
                                   "code_verifier": "wrong"})
    assert bad.status_code == 400
    # A failed attempt must not leave the code usable.
    assert _tokens(mcp, cid, code).status_code == 400


def test_expired_access_token_is_rejected(mcp, rest):
    cid = _register(mcp)
    tok = _tokens(mcp, cid, _code(rest, cid)).json()
    with privileged(), SessionLocal() as db:
        row = db.get(McpOAuthToken, mcp_oauth._hash(tok["access_token"]))
        row.expires_at = row.expires_at - timedelta(hours=2)
        db.commit()
    assert mcp.post("/mcp", headers={"Authorization": f"Bearer {tok['access_token']}"},
                    json={}).status_code == 401


def test_consent_rejects_unregistered_redirect(mcp, rest):
    cid = _register(mcp)
    r = _consent(rest, cid, redirect_uri="http://localhost:1/other")
    assert r.status_code == 400


def test_consent_requires_pkce(mcp, rest):
    cid = _register(mcp)
    assert _consent(rest, cid, code_challenge="").status_code == 400


def test_deny_redirects_with_access_denied(mcp, rest):
    cid = _register(mcp)
    r = rest.post("/api/auth/mcp/authorize", json={
        "approve": False, "client_id": cid, "redirect_uri": REDIRECT, "state": "xyz"})
    assert parse_qs(urlparse(r.json()["redirect_url"]).query)["error"] == ["access_denied"]


def test_read_only_scope_blocks_write_tools(mcp, rest):
    cid = _register(mcp)
    tok = _tokens(mcp, cid, _code(rest, cid, scope="agentira:read")).json()
    auth = {"Authorization": f"Bearer {tok['access_token']}"}
    def call(name):
        return mcp.post("/mcp", headers=auth, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {}}})
    assert call("update_task").status_code == 403
    assert call("delete_project").status_code == 403
    assert call("get_me").status_code == 200


def test_authorize_redirects_to_consent_page(mcp, monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://app.example")
    r = mcp.get("/authorize?client_id=c&state=s", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://app.example/mcp-authorize?client_id=c&state=s"
