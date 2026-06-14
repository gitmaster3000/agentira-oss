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


def create_token(profile_name: str, profile_id: str, role: str) -> str:
    now = int(time.time())
    payload = {
        "sub": profile_name,
        "profile_id": profile_id,
        "role": role,
        "iat": now,
        "exp": now + JWT_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


async def get_current_user_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """Decoded JWT payload — includes `sub`, `profile_id`, `role`."""
    if credentials is None:
        raise HTTPException(401, "Authentication required")
    try:
        return decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


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
