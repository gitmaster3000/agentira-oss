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


async def get_current_user_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """Decoded JWT payload — includes `sub`, `profile_id`, `role`, `org_id`.

    Side effect: pins the request's org context so RLS / app-layer scoping
    filter every query to the caller's org."""
    if credentials is None:
        raise HTTPException(401, "Authentication required")
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
