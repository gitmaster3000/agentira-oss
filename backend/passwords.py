"""Password hashing — bcrypt, with transparent migration off legacy SHA-256.

AP-194 security floor. New passwords are hashed with bcrypt (salted, slow).
Existing accounts created under the old unsalted SHA-256 scheme still verify on
their next login and are rehashed to bcrypt then (`needs_rehash`), so the
legacy scheme drains without a forced password reset.
"""

from __future__ import annotations

import hashlib

import bcrypt

_BCRYPT_ROUNDS = 12
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def hash_password(password: str) -> str:
    """A fresh bcrypt hash for `password`."""
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(_BCRYPT_ROUNDS)
    ).decode("utf-8")


def _is_bcrypt(stored: str) -> bool:
    return stored.startswith(_BCRYPT_PREFIXES)


def verify_password(password: str, stored: str) -> bool:
    """True if `password` matches the stored hash (bcrypt or legacy SHA-256)."""
    if not stored:
        return False
    if _is_bcrypt(stored):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
        except ValueError:
            return False
    # Legacy unsalted SHA-256 — verified for migration, never written anew.
    return hashlib.sha256(password.encode("utf-8")).hexdigest() == stored


def needs_rehash(stored: str) -> bool:
    """True if the stored hash is legacy and should be upgraded on next login."""
    return not _is_bcrypt(stored)
