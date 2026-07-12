"""Harness reset strategy — TRUNCATE must clear rows between tests."""

from __future__ import annotations

from backend.models import Org, Profile
from backend.db import privileged


def test_pg_reset_clears_rows_between_tests(pg):
    with privileged(), pg.SessionLocal() as db:
        db.add(Profile(name="leftover", account_type="human", org_id=pg.org_id))
        db.commit()
        assert db.query(Profile).filter(Profile.name == "leftover").count() == 1


def test_pg_reset_starts_fresh_after_prior_test(pg):
    with privileged(), pg.SessionLocal() as db:
        assert db.query(Profile).filter(Profile.name == "leftover").count() == 0
        assert db.query(Org).filter(Org.id == pg.org_id).count() == 1