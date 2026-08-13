"""Bootstrap admin credential behaviour (quickstart password generation)."""
import os
import pytest

from backend import services
from backend.models import Profile
from backend.db import privileged


@pytest.fixture
def clean_admin_env(monkeypatch):
    for var in ("AGENTIRA_ADMIN_PASSWORD", "RAILWAY_ENVIRONMENT", "AGENTIRA_QUICKSTART"):
        monkeypatch.delenv(var, raising=False)


def _admin(pg):
    with privileged(), pg.SessionLocal() as db:
        return db.query(Profile).filter(Profile.name == "admin").first()


def test_quickstart_generates_password_and_logs_it(pg, clean_admin_env, monkeypatch, caplog):
    monkeypatch.setenv("AGENTIRA_QUICKSTART", "1")
    with privileged(), pg.SessionLocal() as db:
        db.query(Profile).filter(Profile.name == "admin").delete()
        db.commit()

    with caplog.at_level("INFO"):
        services.bootstrap()

    assert _admin(pg) is not None
    lines = [r.message for r in caplog.records if "Admin password:" in r.message]
    assert len(lines) == 1, f"expected exactly one password line, got {lines}"
    password = lines[0].split("Admin password:")[1].strip()
    # 3 groups of 4 from a 54-char alphabet, hyphen-separated: 14 chars, ~69 bits.
    assert len(password) == 14
    assert password.count("-") == 2
    assert password != "admin123"


def test_explicit_password_wins_over_quickstart(pg, clean_admin_env, monkeypatch, caplog):
    monkeypatch.setenv("AGENTIRA_QUICKSTART", "1")
    monkeypatch.setenv("AGENTIRA_ADMIN_PASSWORD", "chosen-by-operator")
    with privileged(), pg.SessionLocal() as db:
        db.query(Profile).filter(Profile.name == "admin").delete()
        db.commit()

    with caplog.at_level("INFO"):
        services.bootstrap()

    assert _admin(pg) is not None
    assert not [r for r in caplog.records if "Admin password:" in r.message]


def test_railway_without_password_still_fails_loud(pg, clean_admin_env, monkeypatch, caplog):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    with privileged(), pg.SessionLocal() as db:
        db.query(Profile).filter(Profile.name == "admin").delete()
        db.commit()

    with caplog.at_level("ERROR"):
        services.bootstrap()

    assert _admin(pg) is None
    assert any("AGENTIRA_ADMIN_PASSWORD is unset" in r.message for r in caplog.records)
