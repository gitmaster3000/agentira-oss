"""Unit and integration tests for attachments, notifications, and project activity."""

import pytest
import tempfile
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend import services


@pytest.fixture(autouse=True)
def test_db(tmp_path):
    """In-memory DB + patched ATTACHMENTS_DIR so no real files are written."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.services.ATTACHMENTS_DIR", str(tmp_path)):
        db = TestSession()
        services._seed_defaults(db)
        db.close()
        yield TestSession


# ── Attachments ───────────────────────────────────────────────────────────────

def test_list_attachments_empty():
    p = services.create_project("P")
    t = services.create_task(p["id"], "T", actor="system")
    assert services.list_attachments(t["id"]) == []


def test_add_and_list_attachment():
    p = services.create_project("P")
    t = services.create_task(p["id"], "T", actor="system")

    att = services.add_attachment(t["id"], "readme.txt", b"hello world", "text/plain", uploaded_by="alice")

    assert att["filename"] == "readme.txt"
    assert att["content_type"] == "text/plain"
    assert att["size_bytes"] == 11
    assert att["uploaded_by"] == "alice"

    listed = services.list_attachments(t["id"])
    assert len(listed) == 1
    assert listed[0]["id"] == att["id"]


def test_multiple_attachments_returned_newest_first():
    p = services.create_project("P")
    t = services.create_task(p["id"], "T", actor="system")

    services.add_attachment(t["id"], "first.txt", b"a", uploaded_by="system")
    services.add_attachment(t["id"], "second.txt", b"bb", uploaded_by="system")

    listed = services.list_attachments(t["id"])
    assert len(listed) == 2
    assert listed[0]["filename"] == "second.txt"  # newest first


def test_get_attachment_returns_path():
    p = services.create_project("P")
    t = services.create_task(p["id"], "T", actor="system")
    att = services.add_attachment(t["id"], "data.bin", b"\x00\x01\x02", uploaded_by="system")

    result = services.get_attachment(att["id"])
    assert result is not None
    meta, file_path = result
    assert meta["id"] == att["id"]
    assert os.path.exists(file_path)


def test_delete_attachment():
    p = services.create_project("P")
    t = services.create_task(p["id"], "T", actor="system")
    att = services.add_attachment(t["id"], "del.txt", b"bye", uploaded_by="system")

    _, file_path = services.get_attachment(att["id"])
    assert os.path.exists(file_path)

    assert services.delete_attachment(att["id"]) is True
    assert services.get_attachment(att["id"]) is None
    assert not os.path.exists(file_path)


def test_delete_nonexistent_attachment_returns_false():
    assert services.delete_attachment("nonexistent-id") is False


def test_attachment_logged_in_activity():
    p = services.create_project("P")
    t = services.create_task(p["id"], "T", actor="system")
    services.add_attachment(t["id"], "log.txt", b"x", uploaded_by="alice")

    activities = services.get_activity(t["id"])
    assert any(a["action"] == "attached" and "log.txt" in a["detail"] for a in activities)


def test_list_attachments_scoped_to_task():
    """Attachments from one task must not appear in another task's list."""
    p = services.create_project("P")
    t1 = services.create_task(p["id"], "T1", actor="system")
    t2 = services.create_task(p["id"], "T2", actor="system")

    services.add_attachment(t1["id"], "only-t1.txt", b"data", uploaded_by="system")

    assert len(services.list_attachments(t1["id"])) == 1
    assert len(services.list_attachments(t2["id"])) == 0


# ── Notifications ─────────────────────────────────────────────────────────────

def test_list_notifications_empty_for_new_user():
    profile = services.create_profile("alice", role="member")
    assert services.list_notifications(profile["id"]) == []


def test_notification_created_on_task_assignment():
    services.create_profile("boss", role="admin")
    worker = services.create_profile("worker", role="member")
    p = services.create_project("P", actor="boss")
    services.add_project_member(p["id"], "worker", actor="boss")

    services.create_task(p["id"], "Do it", assignee="worker", actor="boss")

    notifs = services.list_notifications(worker["id"], unread_only=False)
    assert any(n["type"] == "task.create" for n in notifs)


def test_notification_created_on_project_invite():
    services.create_profile("adder", role="admin")
    target = services.create_profile("target", role="member")
    p = services.create_project("P", actor="adder")

    services.add_project_member(p["id"], "target", actor="adder")

    notifs = services.list_notifications(target["id"], unread_only=False)
    assert any("project.member.add" in n["type"] for n in notifs)


def test_list_notifications_unread_only_filter():
    services.create_profile("boss", role="admin")
    worker = services.create_profile("worker", role="member")
    p = services.create_project("P", actor="boss")
    services.add_project_member(p["id"], "worker", actor="boss")
    services.create_task(p["id"], "T", assignee="worker", actor="boss")

    all_notifs = services.list_notifications(worker["id"], unread_only=False)
    unread = services.list_notifications(worker["id"], unread_only=True)
    assert len(unread) <= len(all_notifs)
    assert all(not n["read"] for n in unread)


def test_mark_notification_read():
    services.create_profile("boss", role="admin")
    worker = services.create_profile("worker", role="member")
    p = services.create_project("P", actor="boss")
    services.add_project_member(p["id"], "worker", actor="boss")
    services.create_task(p["id"], "T", assignee="worker", actor="boss")

    unread = services.list_notifications(worker["id"], unread_only=True)
    assert len(unread) >= 1

    notif_id = unread[0]["id"]
    assert services.mark_notification_read(notif_id) is True

    # Should no longer appear in unread
    still_unread = services.list_notifications(worker["id"], unread_only=True)
    assert all(n["id"] != notif_id for n in still_unread)

    # Should appear in all notifications as read
    all_notifs = services.list_notifications(worker["id"], unread_only=False)
    marked = next(n for n in all_notifs if n["id"] == notif_id)
    assert marked["read"] is True


def test_mark_nonexistent_notification_returns_false():
    assert services.mark_notification_read("does-not-exist") is False


def test_notifications_scoped_to_user():
    """User A's notifications must not appear in User B's list."""
    services.create_profile("boss", role="admin")
    alice = services.create_profile("alice", role="member")
    bob = services.create_profile("bob", role="member")
    p = services.create_project("P", actor="boss")
    services.add_project_member(p["id"], "alice", actor="boss")

    services.create_task(p["id"], "T", assignee="alice", actor="boss")

    alice_notifs = services.list_notifications(alice["id"], unread_only=False)
    bob_notifs = services.list_notifications(bob["id"], unread_only=False)
    assert len(alice_notifs) >= 1
    assert len(bob_notifs) == 0


# ── Project Activity ──────────────────────────────────────────────────────────

def test_get_project_activity_returns_entries():
    p = services.create_project("P", actor="system")
    services.create_task(p["id"], "T1", actor="system")
    services.create_task(p["id"], "T2", actor="system")

    activity = services.get_project_activity(p["id"])
    assert len(activity) >= 3  # project.create + 2x task.create


def test_get_project_activity_newest_first():
    p = services.create_project("P", actor="system")
    t = services.create_task(p["id"], "T", actor="system")
    services.move_task(t["id"], "todo", actor="system")

    activity = services.get_project_activity(p["id"])
    timestamps = [a["created_at"] for a in activity]
    assert timestamps == sorted(timestamps, reverse=True)


def test_get_project_activity_respects_limit():
    p = services.create_project("P", actor="system")
    for i in range(10):
        services.create_task(p["id"], f"T{i}", actor="system")

    activity = services.get_project_activity(p["id"], limit=5)
    assert len(activity) <= 5


def test_get_project_activity_scoped_to_project():
    """Activity from project A must not appear in project B's feed."""
    p1 = services.create_project("P1", actor="system")
    p2 = services.create_project("P2", actor="system")
    services.create_task(p1["id"], "P1 Task", actor="system")

    p2_activity = services.get_project_activity(p2["id"])
    p2_ids = {a["project_id"] for a in p2_activity}
    assert p1["id"] not in p2_ids


def test_get_project_activity_includes_project_id_and_action():
    p = services.create_project("P", actor="system")
    activity = services.get_project_activity(p["id"])
    for entry in activity:
        assert "id" in entry
        assert "action" in entry
        assert "actor" in entry
        assert "created_at" in entry
