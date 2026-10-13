"""Data access for per-user debug telemetry windows. Repos own the SQL."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.db import SessionLocal
from backend.models import ClientDebugSession


def _now() -> datetime:
    return datetime.now(timezone.utc)


def active(org_id: str, user: str) -> ClientDebugSession | None:
    with SessionLocal() as db:
        return (
            db.query(ClientDebugSession)
            .filter(ClientDebugSession.org_id == org_id,
                    ClientDebugSession.profile_name == user,
                    ClientDebugSession.until > _now())
            .order_by(ClientDebugSession.until.desc())
            .first()
        )


def enable(org_id: str, user: str, minutes: int, reason: str, by: str) -> ClientDebugSession:
    """Replace any window for this user with a new one ending in `minutes`."""
    with SessionLocal() as db:
        db.query(ClientDebugSession).filter(
            ClientDebugSession.org_id == org_id,
            ClientDebugSession.profile_name == user,
        ).delete()
        row = ClientDebugSession(
            org_id=org_id, profile_name=user, level="debug",
            until=_now() + timedelta(minutes=minutes),
            reason=reason[:200], created_by=by[:120],
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


def disable(org_id: str, user: str) -> int:
    with SessionLocal() as db:
        n = db.query(ClientDebugSession).filter(
            ClientDebugSession.org_id == org_id,
            ClientDebugSession.profile_name == user,
        ).delete()
        db.commit()
        return n


def list_active(org_id: str) -> list[ClientDebugSession]:
    with SessionLocal() as db:
        return (
            db.query(ClientDebugSession)
            .filter(ClientDebugSession.org_id == org_id,
                    ClientDebugSession.until > _now())
            .order_by(ClientDebugSession.until)
            .all()
        )
