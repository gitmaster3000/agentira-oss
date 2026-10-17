"""MCP OAuth 2.1 (authorization-code + PKCE, dynamic client registration).

Lets Claude (or any MCP client) connect through a browser consent page instead
of a pasted API key. The client never sees the user's API key: it holds a
short-lived access token and a rotating refresh token, both revocable.

Flow: client registers (`/register`) → sends user to `/authorize` (redirects to
the app's consent page) → app calls `approve()` and sends the browser back to
the client with a code → client exchanges it at `/token` (PKCE) → refreshes
with the refresh token before the access token expires.

Scopes: `agentira:read` (read-only tools) and `agentira:write` (all tools).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from backend.db import privileged, SessionLocal
from backend.models import McpOAuthClient, McpOAuthToken, Profile

SCOPE_READ = "agentira:read"
SCOPE_WRITE = "agentira:write"
VALID_SCOPES = {SCOPE_READ, SCOPE_WRITE}
CODE_TTL = timedelta(minutes=5)
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)


class OAuthError(Exception):
    def __init__(self, error: str, description: str = ""):
        super().__init__(description or error)
        self.error = error
        self.description = description


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _pkce_ok(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return secrets.compare_digest(expected, challenge)


def normalize_scope(scope: str | None) -> str:
    """Keep only known scopes; default to read-only. Write implies read."""
    asked = {s for s in (scope or "").split() if s in VALID_SCOPES}
    if SCOPE_WRITE in asked:
        return f"{SCOPE_READ} {SCOPE_WRITE}"
    return SCOPE_READ


def _is_loopback(uri: str) -> bool:
    from urllib.parse import urlparse
    return urlparse(uri).hostname in ("localhost", "127.0.0.1", "::1")


def register_client(metadata: dict) -> dict:
    uris = metadata.get("redirect_uris") or []
    if not uris or not all(isinstance(u, str) for u in uris):
        raise OAuthError("invalid_redirect_uri", "redirect_uris required")
    for u in uris:
        plain_http = u.startswith("http://") and not _is_loopback(u)
        if "://" not in u or plain_http:
            raise OAuthError("invalid_redirect_uri", "redirect URI must be https or loopback")
    client_id = "mcp_" + secrets.token_urlsafe(18)
    name = str(metadata.get("client_name") or "MCP client")[:200]
    with privileged(), SessionLocal() as db:
        db.add(McpOAuthClient(client_id=client_id, client_name=name,
                              redirect_uris=json.dumps(uris)))
        db.commit()
    return {
        "client_id": client_id, "client_name": name, "redirect_uris": uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }


def get_client(client_id: str) -> dict | None:
    with privileged(), SessionLocal() as db:
        c = db.get(McpOAuthClient, client_id)
        if not c:
            return None
        return {"client_id": c.client_id, "client_name": c.client_name,
                "redirect_uris": json.loads(c.redirect_uris)}


def _issue(db, kind: str, client_id: str, profile_id: str, scope: str, ttl: timedelta,
           redirect_uri: str = "", code_challenge: str = "") -> str:
    secret = secrets.token_urlsafe(32)
    db.add(McpOAuthToken(
        token_hash=_hash(secret), kind=kind, client_id=client_id,
        profile_id=profile_id, scope=scope, redirect_uri=redirect_uri,
        code_challenge=code_challenge, expires_at=_now() + ttl))
    return secret


def approve(client_id: str, redirect_uri: str, code_challenge: str, method: str,
            scope: str | None, state: str | None, profile_id: str) -> str:
    """Called by the signed-in consent page. Returns the URL to send the
    browser to (the client's redirect_uri carrying the code)."""
    client = get_client(client_id)
    if not client or redirect_uri not in client["redirect_uris"]:
        raise OAuthError("invalid_request", "unknown client or redirect_uri")
    if not code_challenge or method != "S256":
        raise OAuthError("invalid_request", "PKCE S256 required")
    with privileged(), SessionLocal() as db:
        code = _issue(db, "code", client_id, profile_id, normalize_scope(scope),
                      CODE_TTL, redirect_uri, code_challenge)
        db.commit()
    q = {"code": code}
    if state:
        q["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return redirect_uri + sep + urlencode(q)


def _token_response(db, client_id: str, profile_id: str, scope: str) -> dict:
    access = _issue(db, "access", client_id, profile_id, scope, ACCESS_TTL)
    refresh = _issue(db, "refresh", client_id, profile_id, scope, REFRESH_TTL)
    db.commit()
    return {"access_token": access, "token_type": "Bearer",
            "expires_in": int(ACCESS_TTL.total_seconds()),
            "refresh_token": refresh, "scope": scope}


def _consume(db, secret: str, kind: str, client_id: str) -> McpOAuthToken:
    row = db.get(McpOAuthToken, _hash(secret or ""))
    if (not row or row.kind != kind or row.client_id != client_id
            or row.expires_at < _now()):
        raise OAuthError("invalid_grant")
    if row.used:
        # Replay of a consumed code/refresh token: revoke everything this
        # grant issued (RFC 6749 §10.5 / OAuth 2.1 refresh reuse detection).
        db.query(McpOAuthToken).filter(
            McpOAuthToken.profile_id == row.profile_id,
            McpOAuthToken.client_id == client_id,
        ).delete()
        db.commit()
        raise OAuthError("invalid_grant", "token already used")
    row.used = True
    db.commit()  # burn it even if the caller's later checks fail
    return row


def exchange(form: dict) -> dict:
    grant = form.get("grant_type")
    client_id = form.get("client_id", "")
    with privileged(), SessionLocal() as db:
        if not db.get(McpOAuthClient, client_id):
            raise OAuthError("invalid_client")
        if grant == "authorization_code":
            row = _consume(db, form.get("code", ""), "code", client_id)
            if form.get("redirect_uri") != row.redirect_uri:
                raise OAuthError("invalid_grant", "redirect_uri mismatch")
            if not _pkce_ok(form.get("code_verifier", ""), row.code_challenge):
                raise OAuthError("invalid_grant", "PKCE verification failed")
        elif grant == "refresh_token":
            row = _consume(db, form.get("refresh_token", ""), "refresh", client_id)
        else:
            raise OAuthError("unsupported_grant_type")
        return _token_response(db, client_id, row.profile_id, row.scope)


def validate_access_token(token: str) -> tuple[dict, str] | None:
    """Return (profile_dict, scope) for a live OAuth access token, else None."""
    from backend import services
    with privileged(), SessionLocal() as db:
        row = db.get(McpOAuthToken, _hash(token))
        if not row or row.kind != "access" or row.expires_at < _now():
            return None
        profile = db.get(Profile, row.profile_id)
        if not profile:
            return None
        return services._profile_to_dict(profile), row.scope


def revoke_all(profile_id: str) -> None:
    with privileged(), SessionLocal() as db:
        db.query(McpOAuthToken).filter(McpOAuthToken.profile_id == profile_id).delete()
        db.commit()


# ── Scope enforcement ─────────────────────────────────────────────────────

def is_read_only_call(body: bytes) -> bool:
    """True when every JSON-RPC message in `body` is allowed for a read-only
    token: any non-tool method, or a `tools/call` of get_*/list_*/read_*."""
    try:
        msgs = json.loads(body or b"[]")
    except ValueError:
        return True  # not JSON-RPC; the MCP layer rejects it
    for m in msgs if isinstance(msgs, list) else [msgs]:
        if not isinstance(m, dict) or m.get("method") != "tools/call":
            continue
        name = str((m.get("params") or {}).get("name", ""))
        if not name.startswith(("get_", "list_", "read_")):
            return False
    return True
