"""Regression test for the 2026-07-04 prod OOM: /api/notifications with
unread_only=false returned the profile's ENTIRE notification history —
list_notifications had no LIMIT — while the shell polls it every 30s per
open session. As the table grew, each poll materialized the full history
into ORM objects until the container hit its memory ceiling and was
OOM-killed.

list_notifications must be bounded at the SQL layer.
"""
from __future__ import annotations

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.models import Notification, Profile


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg


def _seed_profile_with_notifications(count: int) -> str:
    with bdb.SessionLocal() as db:
        prof = Profile(name="notif-user", display_name="Notif User")
        db.add(prof)
        db.commit()
        profile_id = prof.id
        for i in range(count):
            db.add(Notification(profile_id=profile_id, type="forge.run.completed",
                                title=f"n{i}", link="/", read=(i % 2 == 0)))
        db.commit()
    return profile_id


def test_list_notifications_bounded_by_default():
    profile_id = _seed_profile_with_notifications(150)
    out = core_services.list_notifications(profile_id, unread_only=False)
    assert len(out) == 100


def test_list_notifications_respects_explicit_limit():
    profile_id = _seed_profile_with_notifications(30)
    out = core_services.list_notifications(profile_id, unread_only=False, limit=10)
    assert len(out) == 10


def test_list_notifications_returns_newest_first():
    profile_id = _seed_profile_with_notifications(120)
    out = core_services.list_notifications(profile_id, unread_only=False)
    titles = [n["title"] for n in out]
    assert titles[0] == "n119"
