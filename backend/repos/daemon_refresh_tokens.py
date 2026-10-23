"""Data access for daemon device refresh tokens. Repos own the SQL.

Every function takes the caller's session; the caller owns the transaction.
"""
from __future__ import annotations

from datetime import datetime

from backend.models import DaemonRefreshToken


def add(db, row: DaemonRefreshToken) -> DaemonRefreshToken:
    db.add(row)
    return row


def get_by_hash(db, token_hash: str) -> DaemonRefreshToken | None:
    return (db.query(DaemonRefreshToken)
              .filter(DaemonRefreshToken.token_hash == token_hash)
              .first())


def mark_used(db, row_id: str, now: datetime) -> bool:
    """Atomically retire a live token. False if someone else already did —
    i.e. a concurrent or replayed exchange."""
    n = (db.query(DaemonRefreshToken)
           .filter(DaemonRefreshToken.id == row_id,
                   DaemonRefreshToken.used_at.is_(None),
                   DaemonRefreshToken.revoked_at.is_(None))
           .update({DaemonRefreshToken.used_at: now,
                    DaemonRefreshToken.last_used_at: now},
                   synchronize_session=False))
    return n == 1


def revoke_family(db, family_id: str, now: datetime) -> None:
    (db.query(DaemonRefreshToken)
       .filter(DaemonRefreshToken.family_id == family_id,
               DaemonRefreshToken.revoked_at.is_(None))
       .update({DaemonRefreshToken.revoked_at: now}, synchronize_session=False))
