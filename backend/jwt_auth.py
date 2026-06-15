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


def create_token(profile_name: str, profile_id: str, role: str,
                 org_id: str | None = None) -> str:
    now = int(time.time())
    payload = {
        "sub": profile_name,
        "profile_id": profile_id,
        "role": role,
        "org_id": org_id,
        "iat": now,
        "exp": now + JWT_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


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
    from backend.models import Profile, Role
    with privileged(), SessionLocal() as db:
        p = db.query(Profile).filter(Profile.name == profile_name).first()
        if not p or not p.org_id:
            return None
        role = db.get(Role, p.role_id)
        return {
            "sub": p.name,
            "profile_id": p.id,
            "role": role.name if role else "admin",
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
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    # Tokens minted before multi-tenancy carry no org_id. Reject them so a
    # stale session can't fall through to the unscoped (system) engine — the
    # user simply re-logs in and gets an org-scoped token.
    if not payload.get("org_id"):
        raise HTTPException(401, "Session out of date — please sign in again.")
    from backend.db import set_current_org
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
    """FastAPI dependency — 403 unless the JWT's role claim == 'admin'.

    Role is taken from the token (set at login). A user whose role is
    changed in the DB must re-login for the new role to take effect.
    """
    if payload.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    return payload["sub"]
