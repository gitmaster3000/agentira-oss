"""MCP OAuth 2.1 flow: discovery, DCR, PKCE login, token, refresh, /mcp auth."""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.testclient import TestClient

from backend import mcp_server
from backend.db import SessionLocal, privileged
from backend.models import Profile, Role

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


@pytest.fixture
def client(pg):
    from backend import services
    with privileged(), SessionLocal() as db:
        role = db.query(Role).filter(Role.name == "member").first()
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        db.add(Profile(name="alice", account_type="human", roles=[role], org_id=pg.org_id,
                       password_hash=services._hash_password("s3cret")))
        db.add(Profile(name="boss", account_type="human", roles=[admin_role], org_id=pg.org_id,
                       password_hash=services._hash_password("s3cret")))
        db.add(Profile(name="bot1", account_type="external_agent", roles=[role], org_id=pg.org_id,
                       password_hash=""))
        db.commit()
    # No lifespan: the MCP session manager is single-use. Auth runs before it,
    # so a non-401 on /mcp (500 here) proves the token was accepted.
    return TestClient(mcp_server.app, base_url="https://mcp.example.com",
                      follow_redirects=False, raise_server_exceptions=False)


def _register(c):
    r = c.post("/register", json={"redirect_uris": [REDIRECT], "client_name": "Claude"})
    assert r.status_code == 201
    return r.json()["client_id"]


def _authorize(c, client_id, password="s3cret", username="alice", **extra):
    return c.post("/authorize", data={
        "client_id": client_id, "redirect_uri": REDIRECT, "state": "xyz",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "response_type": "code", "username": username, "password": password, **extra})


def _profile_of(c, response):
    """Name of the profile an authorize redirect's code was issued for."""
    from backend import mcp_oauth, services
    code = parse_qs(urlparse(response.headers["location"]).query)["code"][0]
    return services.get_profile(mcp_oauth._verify(code, "mcp_code")["sub"])["name"]


def _exchange(c, client_id):
    r = _authorize(c, client_id)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["state"] == ["xyz"]
    return c.post("/token", data={"grant_type": "authorization_code", "code": q["code"][0],
                                  "client_id": client_id, "redirect_uri": REDIRECT,
                                  "code_verifier": VERIFIER})


def test_unauthenticated_mcp_points_to_resource_metadata(client):
    r = client.post("/mcp", json={})
    assert r.status_code == 401
    assert "resource_metadata=\"https://mcp.example.com/.well-known/oauth-protected-resource\"" \
        in r.headers["www-authenticate"]


def test_discovery_documents(client):
    prm = client.get("/.well-known/oauth-protected-resource").json()
    assert prm["authorization_servers"] == ["https://mcp.example.com"]
    asm = client.get("/.well-known/oauth-authorization-server").json()
    assert asm["code_challenge_methods_supported"] == ["S256"]
    assert asm["registration_endpoint"].endswith("/register")


def test_full_flow_gives_working_mcp_token(client):
    cid = _register(client)
    tok = _exchange(client, cid).json()
    assert tok["token_type"] == "Bearer" and tok["refresh_token"]
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                    headers={"Authorization": f"Bearer {tok['access_token']}",
                             "Accept": "application/json, text/event-stream"})
    assert r.status_code != 401


def test_refresh_token_grants_new_access_token(client):
    cid = _register(client)
    tok = _exchange(client, cid).json()
    r = client.post("/token", data={"grant_type": "refresh_token",
                                    "refresh_token": tok["refresh_token"], "client_id": cid})
    assert r.status_code == 200 and r.json()["access_token"]


def test_wrong_password_shows_login_again(client):
    cid = _register(client)
    assert _authorize(client, cid, password="nope").status_code == 401


def test_unregistered_redirect_is_rejected_not_followed(client):
    cid = _register(client)
    r = client.get("/authorize", params={
        "client_id": cid, "redirect_uri": "https://evil.example/cb", "response_type": "code",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256"})
    assert r.status_code == 400


def test_bad_pkce_verifier_fails(client):
    cid = _register(client)
    r = _authorize(client, cid)
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    r = client.post("/token", data={"grant_type": "authorization_code", "code": code,
                                    "client_id": cid, "redirect_uri": REDIRECT,
                                    "code_verifier": "w" * 64})
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_access_token_cannot_be_used_as_refresh(client):
    cid = _register(client)
    tok = _exchange(client, cid).json()
    r = client.post("/token", data={"grant_type": "refresh_token",
                                    "refresh_token": tok["access_token"]})
    assert r.status_code == 400


def test_admin_link_pins_agent_identity(client):
    cid = _register(client)
    r = _authorize(client, cid, username="boss",
                   resource="https://mcp.example.com/mcp?as=bot1")
    assert r.status_code == 302 and _profile_of(client, r) == "bot1"


def test_admin_without_link_gets_picker_then_chosen_identity(client):
    cid = _register(client)
    r = _authorize(client, cid, username="boss")
    assert r.status_code == 200 and "Who is connecting?" in r.text
    import re
    from backend import services
    login = re.search(r'name="login" value="([^"]+)"', r.text).group(1)
    bot_id = next(a["id"] for a in services.list_profiles() if a["name"] == "bot1")
    r = client.post("/authorize", data={
        "client_id": cid, "redirect_uri": REDIRECT, "state": "xyz", "code_challenge": CHALLENGE,
        "code_challenge_method": "S256", "response_type": "code",
        "login": login, "identity": bot_id})
    assert r.status_code == 302 and _profile_of(client, r) == "bot1"


def test_non_admin_cannot_connect_as_agent(client):
    cid = _register(client)
    r = _authorize(client, cid, resource="https://mcp.example.com/mcp?as=bot1")
    assert r.status_code == 403
    r = _authorize(client, cid)  # no link: acts as themselves
    assert _profile_of(client, r) == "alice"
