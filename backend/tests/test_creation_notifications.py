"""Creation notifications: task / bug / epic created → project members, filtered
by each member's per-event, per-channel preferences (in-app, email, push)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.db as bdb
from backend import notify_dispatch, services
from backend.models import Notification, Profile, ProjectMember, PushSubscription, Role
from backend.rest_api import app


@pytest.fixture(autouse=True)
def _sync(monkeypatch):
    """Run the post-commit sends inline and capture them."""
    sent = {"email": [], "push": []}
    monkeypatch.setattr(notify_dispatch, "_spawn", lambda fn: fn())
    monkeypatch.setattr(notify_dispatch.email_sender, "send_email",
                        lambda to, subject, body, html=None: sent["email"].append((to, subject)) or True)
    monkeypatch.setattr(notify_dispatch, "_webpush",
                        lambda sub, payload: sent["push"].append((sub["endpoint"], payload)) or True)
    return sent


@pytest.fixture
def world(pg):
    with bdb.SessionLocal() as db:
        member = db.query(Role).filter(Role.name == "member").first()
        for n in ("alice", "bob"):
            db.add(Profile(name=n, email=f"{n}@x.io", account_type="human",
                           roles=[member], password_hash=""))
        db.commit()
    p = services.create_project("P", actor="alice", members=[])
    with bdb.SessionLocal() as db:
        bob = db.query(Profile).filter_by(name="bob").one()
        db.add(ProjectMember(project_id=p["id"], profile_id=bob.id))
        db.commit()
    return p["id"]


def _notifs(name):
    with bdb.SessionLocal() as db:
        prof = db.query(Profile).filter_by(name=name).one()
        return [n.type for n in db.query(Notification).filter_by(profile_id=prof.id) if n.type.endswith('.created')]


def _prefs(name, prefs):
    with bdb.SessionLocal() as db:
        prof = db.query(Profile).filter_by(name=name).one()
        notify_dispatch.save_prefs(db, prof.id, prefs)
        db.commit()


def test_task_bug_epic_notify_other_members_in_app_by_default(world):
    services.create_task(world, "T", actor="alice")
    services.create_task(world, "B", actor="alice", type="bug")
    services.create_epic(world, "E", actor="alice")
    assert sorted(_notifs("bob")) == ["bug.created", "epic.created", "task.created"]
    assert _notifs("alice") == []  # creator not notified


def test_in_app_opt_out_per_event(world):
    _prefs("bob", {"bug.created": {"in_app": False}})
    services.create_task(world, "B", actor="alice", type="bug")
    services.create_task(world, "T", actor="alice")
    assert _notifs("bob") == ["task.created"]


def test_email_channel(world, _sync):
    services.create_task(world, "T", actor="alice")
    assert _sync["email"] == []  # off by default
    _prefs("bob", {"task.created": {"email": True}})
    services.create_task(world, "T2", actor="alice")
    assert [to for to, _ in _sync["email"]] == ["bob@x.io"]


def test_push_channel(world, _sync):
    with bdb.SessionLocal() as db:
        bob = db.query(Profile).filter_by(name="bob").one()
        db.add(PushSubscription(profile_id=bob.id, endpoint="https://push/1", p256dh="k", auth="a"))
        db.commit()
    _prefs("bob", {"epic.created": {"push": True}})
    services.create_epic(world, "E", actor="alice")
    assert [e for e, _ in _sync["push"]] == ["https://push/1"]


def test_prefs_api_roundtrip(seed_admin):
    _, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    got = c.get("/api/notifications/preferences").json()
    assert got["task.created"] == {"in_app": True, "email": False, "push": False}
    res = c.put("/api/notifications/preferences",
                json={"bug.created": {"email": True, "in_app": False}})
    assert res.status_code == 200
    got = c.get("/api/notifications/preferences").json()
    assert got["bug.created"] == {"in_app": False, "email": True, "push": False}
    assert c.put("/api/notifications/preferences", json={"nope.created": {"email": True}}).status_code == 422


def test_push_subscribe_unsubscribe(seed_admin):
    _, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    sub = {"endpoint": "https://push/9", "keys": {"p256dh": "k", "auth": "a"}}
    assert c.post("/api/notifications/push/subscribe", json=sub).status_code == 200
    assert c.post("/api/notifications/push/subscribe", json=sub).status_code == 200  # idempotent
    with bdb.SessionLocal() as db:
        assert db.query(PushSubscription).count() == 1
    assert c.post("/api/notifications/push/unsubscribe", json={"endpoint": "https://push/9"}).status_code == 200
    with bdb.SessionLocal() as db:
        assert db.query(PushSubscription).count() == 0
