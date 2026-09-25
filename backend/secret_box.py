"""AP-533: symmetric encryption for secrets at rest.

Provider credentials (deploy tokens) must never sit in the DB as clear text.
This wraps Fernet (from `cryptography`, already a dependency) behind a tiny
encrypt/decrypt pair.

Key source: `AGENTIRA_SECRET_KEY` (a url-safe base64 Fernet key). Dev and test
fall back to a fixed, obviously-not-secret key so a fresh checkout works
offline — production MUST set the env var to a real key.

Migration is lazy: `decrypt` returns any value that isn't valid ciphertext
unchanged, so pre-encryption (plaintext) rows keep working and get re-written
as ciphertext the next time they're saved (migrate-on-write).
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

# Deterministic, clearly dev-only key — never used when AGENTIRA_SECRET_KEY is set.
_DEV_KEY = base64.urlsafe_b64encode(hashlib.sha256(b"agentira-dev-only-secret").digest())


def _fernet() -> Fernet:
    key = os.environ.get("AGENTIRA_SECRET_KEY") or _DEV_KEY
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt a secret for storage. None/empty passes through unchanged."""
    if not plaintext:
        return plaintext
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(stored: str | None) -> str | None:
    """Decrypt a stored secret. None/empty passes through; a value that isn't
    valid ciphertext is treated as legacy plaintext and returned as-is."""
    if not stored:
        return stored
    try:
        return _fernet().decrypt(stored.encode()).decode()
    except InvalidToken:
        return stored
