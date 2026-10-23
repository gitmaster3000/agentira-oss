"""Seeding the dedicated browser-test (Playwright) user on a fresh database."""

from backend import e2e_seed, services


def test_ensure_e2e_user_creates_a_working_admin(pg):
    created = e2e_seed.ensure_e2e_user("e2e-admin", "e2e-pass-1234", "e2e-admin@example.test")

    assert created is True
    profile = services.authenticate_user("e2e-admin", "e2e-pass-1234")
    assert profile is not None
    assert "admin" in profile["roles"]
    assert profile["must_change_password"] is False


def test_ensure_e2e_user_is_idempotent(pg):
    e2e_seed.ensure_e2e_user("e2e-admin", "e2e-pass-1234", "e2e-admin@example.test")

    assert e2e_seed.ensure_e2e_user("e2e-admin", "e2e-pass-1234", "e2e-admin@example.test") is False
