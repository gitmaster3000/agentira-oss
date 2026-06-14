"""AP-194 password security floor.

bcrypt for new hashes; legacy unsalted SHA-256 still verifies (so existing
accounts aren't locked out) and is flagged for rehash on next login.
"""

from __future__ import annotations

import hashlib

from backend import passwords


def test_new_hash_is_bcrypt():
    h = passwords.hash_password("hunter2")
    assert h.startswith(("$2a$", "$2b$", "$2y$"))
    assert h != "hunter2"


def test_bcrypt_roundtrip():
    h = passwords.hash_password("correct horse")
    assert passwords.verify_password("correct horse", h)
    assert not passwords.verify_password("wrong horse", h)
    assert not passwords.needs_rehash(h)


def test_legacy_sha256_still_verifies_and_flags_rehash():
    legacy = hashlib.sha256("admin123".encode()).hexdigest()
    assert passwords.verify_password("admin123", legacy)
    assert not passwords.verify_password("nope", legacy)
    assert passwords.needs_rehash(legacy)        # must be upgraded on login


def test_empty_hash_never_verifies():
    assert not passwords.verify_password("anything", "")
    assert not passwords.verify_password("", "")


def test_two_hashes_of_same_password_differ_salted():
    a = passwords.hash_password("same")
    b = passwords.hash_password("same")
    assert a != b                                 # per-hash salt
    assert passwords.verify_password("same", a)
    assert passwords.verify_password("same", b)
