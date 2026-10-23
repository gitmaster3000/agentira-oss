"""Device refresh tokens for the local daemon.

`agentira daemon login` yields a 7-day access JWT. Alongside it we issue a
long-lived (90 days, sliding) refresh token so the daemon can mint a new access
JWT on its own instead of going silently signed-out.

- Only the SHA-256 of a token is stored; the raw value exists once, in the
  login response.
- Every exchange rotates: the presented token is retired and a new one issued.
- Presenting an already-retired token means a copy leaked or was replayed, so
  the whole family (every token from that login) is revoked.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from backend.db import SessionLocal, privileged
from backend.jwt_auth import JWT_EXPIRY_SECONDS, create_token
from backend.models import DaemonRefreshToken, Profile
from backend.repos import daemon_refresh_tokens as repo

REFRESH_TTL = timedelta(days=90)


class RefreshRejected(Exception):
    """The refresh token is unknown, expired, revoked, reused or no longer
    allowed. Callers answer a generic 401 — never say which."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _mint(db, *, profile_id: str, org_id: str, family_id: str,
          device_name: str | None, daemon_id: str | None, now: datetime) -> str:
    raw = secrets.token_urlsafe(48)
    repo.add(db, DaemonRefreshToken(
        profile_id=profile_id, org_id=org_id, family_id=family_id,
        token_hash=_hash(raw), device_name=(device_name or None) and device_name[:120],
        daemon_id=(daemon_id or None) and daemon_id[:64],
        created_at=now, expires_at=now + REFRESH_TTL))
    return raw


def issue(*, profile_id: str, org_id: str, device_name: str | None = None,
          daemon_id: str | None = None) -> str:
    """Start a new token family at daemon login; returns the raw token."""
    now = datetime.now(timezone.utc)
    with privileged(), SessionLocal() as db:
        raw = _mint(db, profile_id=profile_id, org_id=org_id,
                    family_id=uuid.uuid4().hex, device_name=device_name,
                    daemon_id=daemon_id, now=now)
        db.commit()
    return raw


def exchange(refresh_token: str) -> dict:
    """Trade a live refresh token for a fresh access JWT + rotated refresh
    token. Raises RefreshRejected on any failure."""
    if not refresh_token:
        raise RefreshRejected()
    now = datetime.now(timezone.utc)
    # Unauthenticated entry point: there is no org context yet, the token
    # itself is the credential.
    with privileged(), SessionLocal() as db:
        row = repo.get_by_hash(db, _hash(refresh_token))
        if row is None:
            raise RefreshRejected()
        if row.revoked_at is not None:
            raise RefreshRejected()
        if row.used_at is not None:
            repo.revoke_family(db, row.family_id, now)  # replay → burn the chain
            db.commit()
            raise RefreshRejected()
        if row.expires_at <= now:
            raise RefreshRejected()

        profile = db.get(Profile, row.profile_id)
        roles = profile.role_names if profile else []
        if (profile is None or profile.archived_at is not None
                or not profile.org_id or "admin" not in roles):
            repo.revoke_family(db, row.family_id, now)
            db.commit()
            raise RefreshRejected()

        if not repo.mark_used(db, row.id, now):  # lost a race with a replay
            repo.revoke_family(db, row.family_id, now)
            db.commit()
            raise RefreshRejected()
        new_refresh = _mint(db, profile_id=row.profile_id, org_id=row.org_id,
                            family_id=row.family_id, device_name=row.device_name,
                            daemon_id=row.daemon_id, now=now)
        token = create_token(profile.name, profile.id, roles, profile.org_id)
        db.commit()
    return {"token": token, "refresh_token": new_refresh,
            "expires_in": JWT_EXPIRY_SECONDS}


def revoke(refresh_token: str) -> None:
    """Revoke the whole family of the presented token (daemon logout). Unknown
    tokens are ignored."""
    with privileged(), SessionLocal() as db:
        row = repo.get_by_hash(db, _hash(refresh_token or ""))
        if row is not None:
            repo.revoke_family(db, row.family_id, datetime.now(timezone.utc))
            db.commit()
