"""JWT authentication for the REST API."""

import os
import time
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

JWT_SECRET = os.getenv("JWT_SECRET", "")
if not JWT_SECRET:
    # AP-194: in production a per-process random secret silently invalidates
    # every token on each restart — refuse to boot instead. Dev keeps the
    # convenience fallback.
    if os.getenv("RAILWAY_ENVIRONMENT") is not None:
        raise RuntimeError(
            "JWT_SECRET must be set in production. Generate one with "
            "`python -c \"import secrets; print(secrets.token_hex(32))\"` and "
            "set it in the environment.")
    import secrets
    JWT_SECRET = secrets.token_hex(32)
    print("WARNING: JWT_SECRET not set — using random secret (tokens won't survive restarts)")

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 7 * 24 * 3600  # 7 days

_bearer_scheme = HTTPBearer(auto_error=False)


def create_token(profile_name: str, profile_id: str, roles,
                 org_id: str | None = None) -> str:
    # RBAC: the token carries a `roles` LIST. A single string is still accepted
    # (wrapped) for back-compat. A legacy `role` claim (first role) is emitted
    # too so old readers keep working during rollout.
    role_list = [roles] if isinstance(roles, str) else list(roles or [])
    now = int(time.time())
    payload = {
        "sub": profile_name,
        "profile_id": profile_id,
        "roles": role_list,
        "role": role_list[0] if role_list else None,
        "org_id": org_id,
        "iat": now,
        "exp": now + JWT_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def payload_roles(payload: dict) -> list[str]:
    """Roles from a token payload — prefers the `roles` list, falls back to a
    legacy single `role` claim so pre-RBAC tokens still authorize."""
    roles = payload.get("roles")
    if roles:
        return roles
    legacy = payload.get("role")
    return [legacy] if legacy else []


def _dev_bypass_payload(token: str) -> dict | None:
    """Dev-only auth shortcut. When AGENTIRA_DEV_API_KEY is set and the bearer
    token matches it, authenticate as the configured dev profile
    (AGENTIRA_DEV_PROFILE, default 'admin') — its real org_id/role. Lets a local
    test daemon connect with ONE static key: no browser login, no JWT minting.

    GATING IS CONFIG, NOT CODE: provider-agnostic (Railway/AWS/GCP/bare docker
    all look identical here). The bypass activates only when AGENTIRA_ENV is
    explicitly 'dev'. The default is 'prod', so it is fail-safe OFF everywhere
    unless a dev config opts in — even if AGENTIRA_DEV_API_KEY somehow leaks
    into a prod environment, it does nothing without AGENTIRA_ENV=dev."""
    if os.getenv("AGENTIRA_ENV", "prod").strip().lower() != "dev":
        return None
    dev_key = os.getenv("AGENTIRA_DEV_API_KEY", "")
    if not dev_key or token != dev_key:
        return None
    profile_name = os.getenv("AGENTIRA_DEV_PROFILE", "admin")
    from backend.db import privileged, SessionLocal
    from backend.models import Profile
    with privileged(), SessionLocal() as db:
        p = db.query(Profile).filter(Profile.name == profile_name).first()
        if not p or not p.org_id:
            return None
        roles = p.role_names or ["admin"]
        return {
            "sub": p.name,
            "profile_id": p.id,
            "roles": roles,
            "role": roles[0],
            "org_id": p.org_id,
            "dev_bypass": True,
        }


async def get_current_user_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """Decoded JWT payload — includes `sub`, `profile_id`, `role`, `org_id`.

    Side effect: pins the request's org context so RLS / app-layer scoping
    filter every query to the caller's org."""
    if credentials is None:
        raise HTTPException(401, "Authentication required")
    # Dev-only static-key bypass (no-op in prod / when AGENTIRA_DEV_API_KEY unset).
    dev = _dev_bypass_payload(credentials.credentials)
    if dev is not None:
        from backend.db import set_current_org
        set_current_org(dev["org_id"])
        return dev
    from backend.db import set_current_org
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        # Not a JWT — fall back to an agent API key. Agents curl authed REST
        # endpoints (e.g. attachment download) with $AGENTIRA_API_KEY.
        from backend import services
        try:
            prof = services.validate_api_key(credentials.credentials)
        except ValueError:
            raise HTTPException(401, "Invalid token")
        if not prof.get("org_id"):
            raise HTTPException(401, "Invalid token")
        set_current_org(prof["org_id"])
        return {
            "sub": prof["name"], "profile_id": prof["id"],
            "roles": prof.get("roles", []), "role": prof.get("role"),
            "org_id": prof["org_id"],
        }
    # Tokens minted before multi-tenancy carry no org_id. Reject them so a
    # stale session can't fall through to the unscoped (system) engine — the
    # user simply re-logs in and gets an org-scoped token.
    if not payload.get("org_id"):
        raise HTTPException(401, "Session out of date — please sign in again.")
    set_current_org(payload.get("org_id"))
    return payload


async def get_current_user(
    payload: dict = Depends(get_current_user_payload),
) -> str:
    """FastAPI dependency — returns the actor (profile name) from JWT."""
    return payload["sub"]


async def require_admin(
    payload: dict = Depends(get_current_user_payload),
) -> str:
    """FastAPI dependency — 403 unless 'admin' is among the JWT's roles.

    Roles are taken from the token (set at login). A user whose roles are
    changed in the DB must re-login for the change to take effect.
    """
    if "admin" not in payload_roles(payload):
        raise HTTPException(403, "Admin only")
    return payload["sub"]
