"""OAuth 2.1 for the MCP endpoint (Claude custom connectors, MCP authorization spec).

Stateless: client ids, authorization codes and tokens are all signed JWTs
(JWT_SECRET), so no tables and no new services. Flow:

  1. Client hits /mcp without a token -> 401 + WWW-Authenticate pointing at
     /.well-known/oauth-protected-resource.
  2. Client discovers /.well-known/oauth-authorization-server, registers via
     POST /register (RFC 7591), sends the user to GET /authorize.
  3. User signs in on the Agentira login form (POST /authorize) and is
     redirected back with a code. PKCE (S256) is mandatory.
  4. Client exchanges the code at POST /token for an access + refresh token.
     The access token is accepted by the /mcp middleware like an API key.

Static API keys keep working unchanged.
"""

import base64
import hashlib
import html
import os
import time
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jwt
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from backend import services
from backend.db import privileged, set_current_org
from backend.jwt_auth import JWT_ALGORITHM, JWT_SECRET, decode_token

ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600
CODE_TTL = 300
SCOPE = "mcp"


def issuer(request: Request) -> str:
    """Public base URL of this service. MCP_PUBLIC_URL wins; otherwise derive
    from the (proxy-forwarded) request so Railway works with no extra config."""
    configured = os.getenv("MCP_PUBLIC_URL", "").rstrip("/")
    if configured:
        return configured
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return f"{proto}://{host}"


def _sign(typ: str, ttl: int, **claims) -> str:
    now = int(time.time())
    return jwt.encode({"typ": typ, "iat": now, "exp": now + ttl, **claims},
                      JWT_SECRET, algorithm=JWT_ALGORITHM)


def _verify(token: str, typ: str) -> dict | None:
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    return claims if claims.get("typ") == typ else None


def verify_access_token(token: str) -> dict | None:
    """Profile dict for a valid OAuth access token, else None."""
    claims = _verify(token, "mcp_access")
    if not claims:
        return None
    return _profile(claims["sub"])


def _profile(profile_id: str) -> dict | None:
    with privileged():
        return services.get_profile(profile_id)


def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status)


def _pkce_ok(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == challenge


def resource_metadata_url(request: Request) -> str:
    return f"{issuer(request)}/.well-known/oauth-protected-resource"


# ── Discovery ───────────────────────────────────────────────────────────────

async def protected_resource_metadata(request: Request):
    base = issuer(request)
    return JSONResponse({
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [SCOPE],
    })


async def authorization_server_metadata(request: Request):
    base = issuer(request)
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPE],
        **({"client_id_metadata_document_supported": True} if _metadata_hosts_setting() else {}),
    })


# ── Dynamic client registration (RFC 7591) ──────────────────────────────────

async def register(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _oauth_error("invalid_client_metadata", "JSON body required")
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) for u in uris):
        return _oauth_error("invalid_redirect_uri", "redirect_uris required")
    # The client id is a signed, self-describing token: no registry to store.
    client_id = _sign("mcp_client", 10 * 365 * 24 * 3600, redirect_uris=uris)
    return JSONResponse({
        "client_id": client_id,
        "client_name": body.get("client_name", "MCP client"),
        "redirect_uris": uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }, status_code=201)


# ── Authorization (login + consent in one step) ─────────────────────────────

_FIELDS = ("client_id", "redirect_uri", "state", "code_challenge", "code_challenge_method", "resource")


# Client ID Metadata Documents: newer Claude clients send an https URL as client_id and publish
# { client_id, redirect_uris } there instead of registering. Only approved hosts, no redirects, 64 KB cap.
# MCP_CLIENT_METADATA_HOSTS (comma-separated) replaces the default Claude hosts and also makes discovery advertise the
# feature; left unset, Claude's hosts are accepted but not advertised, so other clients keep registering as before.
CLAUDE_HOSTS = {"claude.ai", "claude.com"}


def _metadata_hosts_setting() -> set[str]:
    return {h.strip().lower() for h in os.getenv("MCP_CLIENT_METADATA_HOSTS", "").split(",") if h.strip()}
_cimd_cache: dict[str, tuple[float, dict | None]] = {}


def _is_loopback(url: str) -> bool:
    u = urlparse(url)
    return u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1")


async def _client(client_id: str) -> dict | None:
    """A client we registered (signed id), or a metadata document served by Claude."""
    signed = _verify(client_id, "mcp_client")
    if signed:
        return signed
    if not client_id.startswith("https://") or urlparse(client_id).hostname not in (_metadata_hosts_setting() or CLAUDE_HOSTS):
        return None
    hit = _cimd_cache.get(client_id)
    if hit and hit[0] > time.time():
        return hit[1]
    client = None
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=5) as http:
            r = await http.get(client_id, headers={"accept": "application/json"})
        doc = r.json() if r.status_code == 200 and len(r.content) <= 65536 else {}
        uris = doc.get("redirect_uris")
        if doc.get("client_id") == client_id and isinstance(uris, list):
            client = {"redirect_uris": [u for u in uris if isinstance(u, str)], "loopback_any_port": True}
    except (httpx.HTTPError, ValueError):
        pass
    _cimd_cache[client_id] = (time.time() + (3600 if client else 60), client)
    if len(_cimd_cache) > 100:
        _cimd_cache.clear()
    return client


def _redirect_ok(client: dict, uri: str) -> bool:
    if uri in client["redirect_uris"]:
        return True
    # RFC 8252: a native app picks a free port at sign-in time, so loopback redirects match on path only.
    return bool(client.get("loopback_any_port") and _is_loopback(uri) and any(
        _is_loopback(r) and urlparse(r).path == urlparse(uri).path for r in client["redirect_uris"]))


async def _validate_authorize(params: dict) -> str | None:
    """Return an error message, or None when the request is acceptable.
    Never redirect to an unvalidated redirect_uri."""
    client = await _client(params.get("client_id", ""))
    if not client:
        return "Unknown client."
    if not _redirect_ok(client, params.get("redirect_uri", "")):
        return "Redirect address is not registered for this client."
    if params.get("response_type", "code") != "code":
        return "Unsupported response type."
    if not params.get("code_challenge") or params.get("code_challenge_method") != "S256":
        return "PKCE (S256) is required."
    return None


def _login_page(params: dict, error: str = "", status: int = 200) -> HTMLResponse:
    hidden = _hidden(params)
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect to Agentira</title><style>
body{{font:16px system-ui,sans-serif;background:#f6f6f7;display:grid;place-items:center;min-height:100vh;margin:0}}
form{{background:#fff;padding:32px;border-radius:12px;width:min(360px,90vw);box-shadow:0 2px 12px #0001}}
h1{{font-size:20px;margin:0 0 4px}}p{{color:#555;margin:0 0 20px}}
input[type=text],input[type=password]{{width:100%;box-sizing:border-box;padding:10px;margin:0 0 12px;border:1px solid #ccc;border-radius:8px;font:inherit}}
button{{width:100%;padding:11px;border:0;border-radius:8px;background:#111;color:#fff;font:inherit;cursor:pointer}}
.err{{color:#b00020}}</style></head><body>
<form method="post" action="/authorize"><h1>Connect to Agentira</h1>
<p>Sign in to let this app use your Agentira account.</p>{err}{hidden}
<input type="text" name="username" placeholder="Username or email" autocomplete="username" required autofocus>
<input type="password" name="password" placeholder="Password" autocomplete="current-password" required>
<button type="submit">Sign in and allow</button></form></body></html>""", status_code=status)


def _hidden(params: dict) -> str:
    return "".join(
        f'<input type="hidden" name="{k}" value="{html.escape(params.get(k, ""))}">'
        for k in _FIELDS + ("response_type",))


def _agent_name_from_resource(resource: str) -> str:
    """The admin-copied connector link is `<mcp>/mcp?as=<agent>`; Claude sends
    it back as the `resource` parameter."""
    return (parse_qs(urlparse(resource or "").query).get("as") or [""])[0]


def _agent_identities(profile: dict) -> list[dict]:
    """Agent identities this user may connect as. Admins only."""
    if "admin" not in (profile.get("roles") or []):
        return []
    set_current_org(profile["org_id"])
    try:
        return services.list_service_accounts()
    finally:
        set_current_org(None)


def _picker_page(params: dict, profile: dict, agents: list[dict]) -> HTMLResponse:
    choices = [(profile["id"], f'Myself ({profile["display_name"]})')] + [
        (a["id"], f'Agent: {a["display_name"]}') for a in agents]
    radios = "".join(
        f'<label><input type="radio" name="identity" value="{html.escape(i)}"'
        f'{" checked" if n == 0 else ""}> {html.escape(label)}</label>'
        for n, (i, label) in enumerate(choices))
    login = _sign("mcp_login", CODE_TTL, sub=profile["id"])
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect to Agentira</title><style>
body{{font:16px system-ui,sans-serif;background:#f6f6f7;display:grid;place-items:center;min-height:100vh;margin:0}}
form{{background:#fff;padding:32px;border-radius:12px;width:min(360px,90vw);box-shadow:0 2px 12px #0001}}
h1{{font-size:20px;margin:0 0 4px}}p{{color:#555;margin:0 0 20px}}
label{{display:block;padding:10px;border:1px solid #ddd;border-radius:8px;margin:0 0 8px;cursor:pointer}}
button{{width:100%;padding:11px;border:0;border-radius:8px;background:#111;color:#fff;font:inherit;cursor:pointer;margin-top:8px}}
</style></head><body><form method="post" action="/authorize"><h1>Who is connecting?</h1>
<p>Choose the identity this connection acts as.</p>{radios}{_hidden(params)}
<input type="hidden" name="login" value="{html.escape(login)}">
<button type="submit">Connect</button></form></body></html>""")


def _redirect_with_code(form: dict, profile_id: str) -> RedirectResponse:
    code = _sign("mcp_code", CODE_TTL, sub=profile_id, cid=form["client_id"],
                 ru=form["redirect_uri"], cc=form["code_challenge"])
    query = {"code": code}
    if form.get("state"):
        query["state"] = form["state"]
    sep = "&" if "?" in form["redirect_uri"] else "?"
    return RedirectResponse(form["redirect_uri"] + sep + urlencode(query), status_code=302)


def _after_sign_in(form: dict, profile: dict):
    """The signed-in user is known (password or web-app handoff): pick who the connection acts as."""
    agents = _agent_identities(profile)

    # Link copied from the admin menu pins the agent: `.../mcp?as=<agent>`.
    wanted = _agent_name_from_resource(form.get("resource", ""))
    if wanted:
        agent = next((a for a in agents if a["name"] == wanted), None)
        if not agent:
            return _login_page(form, "Only an admin can connect as this agent.", status=403)
        return _redirect_with_code(form, agent["id"])
    if agents:
        return _picker_page(form, profile, agents)
    return _redirect_with_code(form, profile["id"])


# ── Sign-in handoff from the Agentira web app ───────────────────────────────
# A user already signed in to Agentira should not type a password again. With MCP_SSO_FRONTEND_URL set, the
# authorize page sends them to <frontend>/mcp-connect, which form-POSTs their web login (a JWT) to /authorize/sso.
# Unset, nothing changes. Any failure falls back to the password page (`sso=0`), so there is no loop.

def _sso_frontend() -> str:
    return os.getenv("MCP_SSO_FRONTEND_URL", "").strip().rstrip("/")


def _origin_of(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}"


async def authorize_sso(request: Request):
    form = dict(await request.form())
    frontend = _sso_frontend()
    # Origin must be the web app: blocks a third-party page posting someone else's token into the victim's browser.
    if not frontend or request.headers.get("origin") != _origin_of(frontend):
        return HTMLResponse("This sign-in must come from Agentira.", status_code=403)
    error = await _validate_authorize(form)
    if error:
        return HTMLResponse(html.escape(error), status_code=400)
    profile = None
    try:
        profile_id = decode_token(form.get("token", "")).get("profile_id")
        profile = profile_id and _profile(profile_id)
    except jwt.InvalidTokenError:
        pass
    if not profile:
        fields = {k: form.get(k, "") for k in _FIELDS + ("response_type",)}
        return RedirectResponse(f"{issuer(request)}/authorize?{urlencode({**fields, 'sso': '0'})}", status_code=303)
    return _after_sign_in(form, profile)



async def authorize(request: Request):
    if request.method == "GET":
        params = dict(request.query_params)
        error = await _validate_authorize(params)
        if error:
            return HTMLResponse(html.escape(error), status_code=400)
        if _sso_frontend() and params.get("sso") != "0":
            back = f"{issuer(request)}/authorize?{urlencode(params)}"
            return RedirectResponse(f"{_sso_frontend()}/mcp-connect?{urlencode({'return': back})}", status_code=302)
        return _login_page(params)

    form = dict(await request.form())
    error = await _validate_authorize(form)
    if error:
        return HTMLResponse(html.escape(error), status_code=400)
    # Step 2: admin picked an identity on the "Who is connecting?" page.
    if form.get("login"):
        claims = _verify(form["login"], "mcp_login")
        profile = claims and _profile(claims["sub"])
        if not profile:
            return HTMLResponse("Sign-in expired. Start again.", status_code=400)
        allowed = {profile["id"]} | {a["id"] for a in _agent_identities(profile)}
        if form.get("identity") not in allowed:
            return HTMLResponse("You can't connect as that identity.", status_code=403)
        return _redirect_with_code(form, form["identity"])

    # Step 1: password sign-in.
    profile = services.authenticate_user(form.get("username", "").strip(), form.get("password", ""))
    if not profile:
        return _login_page(form, "Wrong username or password.", status=401)
    return _after_sign_in(form, profile)


# ── Token endpoint ──────────────────────────────────────────────────────────

def _token_response(profile_id: str, client_id: str) -> JSONResponse:
    return JSONResponse({
        "access_token": _sign("mcp_access", ACCESS_TTL, sub=profile_id),
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL,
        "refresh_token": _sign("mcp_refresh", REFRESH_TTL, sub=profile_id, cid=client_id),
        "scope": SCOPE,
    }, headers={"Cache-Control": "no-store"})


async def token(request: Request):
    form = dict(await request.form())
    grant = form.get("grant_type")

    if grant == "authorization_code":
        claims = _verify(form.get("code", ""), "mcp_code")
        if not claims:
            return _oauth_error("invalid_grant", "Code is invalid or expired")
        if claims["cid"] != form.get("client_id") or claims["ru"] != form.get("redirect_uri"):
            return _oauth_error("invalid_grant", "Client or redirect mismatch")
        if not _pkce_ok(form.get("code_verifier", ""), claims["cc"]):
            return _oauth_error("invalid_grant", "PKCE verification failed")
        if not _profile(claims["sub"]):
            return _oauth_error("invalid_grant", "Account no longer exists")
        return _token_response(claims["sub"], claims["cid"])

    if grant == "refresh_token":
        claims = _verify(form.get("refresh_token", ""), "mcp_refresh")
        if not claims or (form.get("client_id") and form["client_id"] != claims["cid"]):
            return _oauth_error("invalid_grant", "Refresh token is invalid or expired")
        if not _profile(claims["sub"]):
            return _oauth_error("invalid_grant", "Account no longer exists")
        return _token_response(claims["sub"], claims["cid"])

    return _oauth_error("unsupported_grant_type", "Use authorization_code or refresh_token")


routes = [
    Route("/.well-known/oauth-protected-resource", protected_resource_metadata),
    Route("/.well-known/oauth-protected-resource/mcp", protected_resource_metadata),
    Route("/.well-known/oauth-authorization-server", authorization_server_metadata),
    Route("/register", register, methods=["POST"]),
    Route("/authorize/sso", authorize_sso, methods=["POST"]),
    Route("/authorize", authorize, methods=["GET", "POST"]),
    Route("/token", token, methods=["POST"]),
]
