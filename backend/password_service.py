"""AP-306: password lifecycle — admin reset, self-change, forgot/reset-by-token.

Deliberately kept out of services.py: password handling is its own concern
(hashing policy, reset tokens, the must-change flag, reset emails). REST/MCP
call PasswordService; services.py is not in the path.

All DB access goes through ProfileRepository so the query surface this feature
needs lives in one place instead of scattered `db.query(Profile)` calls.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from backend.db import SessionLocal, privileged
from backend.models import Profile
from backend import passwords, email_sender

RESET_TOKEN_TTL = timedelta(hours=1)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProfileRepository:
    """Data-access for Profile rows. Bound to a session; does NOT own the
    session lifecycle or commits — the caller does. Org isolation is handled
    by the session's RLS/org context, same as everywhere else."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, profile_id: str) -> Profile | None:
        return self.db.get(Profile, profile_id)

    def by_name(self, name: str) -> Profile | None:
        return self.db.query(Profile).filter(Profile.name == name).first()

    def by_email(self, email: str) -> Profile | None:
        return self.db.query(Profile).filter(Profile.email == email).first()

    def by_reset_token(self, token: str) -> Profile | None:
        return self.db.query(Profile).filter(Profile.reset_token == token).first()


class PasswordService:
    """Password lifecycle operations. Each method owns its session.

    Forgot/reset-by-token run privileged() (cross-org: we don't know the org
    from an email or token) — same bypass-RLS pattern login uses. Admin reset
    and self-change run in the request's org context so RLS scopes them."""

    def _apply(self, p: Profile, new_password: str, *, must_change: bool) -> None:
        """Set hash + must-change flag and clear any outstanding reset token."""
        if not new_password:
            raise ValueError("password cannot be empty")
        p.password_hash = passwords.hash_password(new_password)
        p.must_change_password = must_change
        p.reset_token = None
        p.reset_token_expires = None

    def admin_set_password(self, profile_id: str,
                           new_password: str | None = None) -> dict | None:
        """Admin sets/resets a member's password. No password given → generate
        a temporary one. Either way the account is flagged to force a change on
        next login. Returns {"temp_password": <str|None>}, or None if no such
        profile (in the admin's org)."""
        temp = None
        with SessionLocal() as db:
            p = ProfileRepository(db).get(profile_id)
            if not p:
                return None
            if not new_password:
                temp = secrets.token_urlsafe(9)
                new_password = temp
            self._apply(p, new_password, must_change=True)
            db.commit()
        return {"temp_password": temp}

    def change_own_password(self, actor_name: str, new_password: str) -> None:
        """Change the logged-in user's own password. JWT auth is sufficient
        proof of identity — no re-entry of the current password required.
        Clears must_change."""
        with SessionLocal() as db:
            p = ProfileRepository(db).by_name(actor_name)
            if not p:
                raise ValueError("Profile not found")
            self._apply(p, new_password, must_change=False)
            db.commit()

    def request_reset(self, email: str) -> str | None:
        """Issue a time-limited reset token and email the link. Silent no-op if
        the email is unknown — never reveal whether an address is registered.
        Returns the token (None if no account) so dev mode can surface it; the
        REST layer must never expose it outside dev."""
        email = (email or "").strip().lower()
        if "@" not in email:
            return None
        with privileged(), SessionLocal() as db:
            p = ProfileRepository(db).by_email(email)
            if not p:
                return None
            # ponytail: token stored plaintext — short-lived, single-use.
            token = secrets.token_urlsafe(32)
            p.reset_token = token
            p.reset_token_expires = _utcnow() + RESET_TOKEN_TTL
            db.commit()
            display_name = p.display_name or p.name
        email_sender.send_password_reset_email(email, display_name, token)
        return token

    def reset_with_token(self, token: str, new_password: str) -> bool:
        """Consume a reset token and set a new password. False if the token is
        unknown or expired."""
        if not token:
            return False
        with privileged(), SessionLocal() as db:
            p = ProfileRepository(db).by_reset_token(token)
            if not p or not p.reset_token_expires or p.reset_token_expires < _utcnow():
                return False
            self._apply(p, new_password, must_change=False)
            db.commit()
            return True


# Stateless singleton — safe to share across requests.
password_service = PasswordService()
