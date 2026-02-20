"""Unit tests for attachment upload and notification ownership validation."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend import services


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession):
        db = TestSession()
        services._seed_defaults(db)
        db.close()
        yield TestSession


# ── Attachment tests ────────────────────────────────────────────────────────────

def test_upload_attachment():
    services.create_profile("uploader", role="member")
    p = services.create_project("Attach Project", actor="uploader")
    t = services.create_task(p["id"], "Task with files", actor="uploader")

    att = services.add_attachment(t["id"], "proof.txt", b"hello world", "text/plain", uploaded_by="uploader")

    assert att["filename"] == "proof.txt"
    assert att["size_bytes"] == 11
    assert att["uploaded_by"] == "uploader"
    assert att["task_id"] == t["id"]


def test_list_attachments_empty():
    services.create_profile("user1", role="member")
    p = services.create_project("Empty Attach Project", actor="user1")
    t = services.create_task(p["id"], "No files task", actor="user1")

    result = services.list_attachments(t["id"])
    assert result == []


def test_list_attachments_returns_uploaded():
    services.create_profile("user2", role="member")
    p = services.create_project("Multi Attach Project", actor="user2")
    t = services.create_task(p["id"], "Multi file task", actor="user2")

    services.add_attachment(t["id"], "a.txt", b"aaa", "text/plain", uploaded_by="user2")
    services.add_attachment(t["id"], "b.txt", b"bbbb", "text/plain", uploaded_by="user2")

    result = services.list_attachments(t["id"])
    assert len(result) == 2
    filenames = {r["filename"] for r in result}
    assert filenames == {"a.txt", "b.txt"}


def test_attachments_count_in_get_task():
    services.create_profile("counter1", role="member")
    p = services.create_project("Count Project", actor="counter1")
    t = services.create_task(p["id"], "Count task", actor="counter1")

    assert services.get_task(t["id"])["attachments_count"] == 0

    services.add_attachment(t["id"], "f1.txt", b"x", "text/plain", uploaded_by="counter1")
    services.add_attachment(t["id"], "f2.txt", b"y", "text/plain", uploaded_by="counter1")

    assert services.get_task(t["id"])["attachments_count"] == 2


def test_attachments_count_in_list_tasks():
    services.create_profile("counter2", role="member")
    p = services.create_project("Count List Project", actor="counter2")
    t1 = services.create_task(p["id"], "Task A", actor="counter2")
    t2 = services.create_task(p["id"], "Task B", actor="counter2")

    services.add_attachment(t1["id"], "a.txt", b"a", "text/plain", uploaded_by="counter2")

    tasks = services.list_tasks(project_id=p["id"], actor="counter2")
    counts = {t["id"]: t["attachments_count"] for t in tasks}
    assert counts[t1["id"]] == 1
    assert counts[t2["id"]] == 0


def test_upload_attachment_unknown_task_raises():
    with pytest.raises(ValueError, match="not found"):
        services.add_attachment("nonexistent", "x.txt", b"x", "text/plain", uploaded_by="system")


# ── Notification ownership tests ────────────────────────────────────────────────

def test_mark_notification_read_correct_owner():
    services.create_profile("inviter", role="admin")
    target = services.create_profile("notif_owner", role="member")
    p = services.create_project("Notif Project", actor="inviter")
    services.add_project_member(p["id"], "notif_owner", actor="inviter")

    notifs = services.list_notifications(target["id"], unread_only=True)
    assert len(notifs) >= 1
    notif_id = notifs[0]["id"]

    result = services.mark_notification_read(notif_id, actor_profile_id=target["id"])
    assert result is True

    remaining = services.list_notifications(target["id"], unread_only=True)
    assert all(n["id"] != notif_id for n in remaining)


def test_mark_notification_read_wrong_owner_rejected():
    services.create_profile("inviter2", role="admin")
    target2 = services.create_profile("notif_owner2", role="member")
    other = services.create_profile("other_user", role="member")
    p = services.create_project("Notif Project 2", actor="inviter2")
    services.add_project_member(p["id"], "notif_owner2", actor="inviter2")

    notifs = services.list_notifications(target2["id"], unread_only=True)
    assert len(notifs) >= 1
    notif_id = notifs[0]["id"]

    # other_user tries to mark notif_owner2's notification as read — must be rejected
    result = services.mark_notification_read(notif_id, actor_profile_id=other["id"])
    assert result is False

    # Notification must still be unread
    remaining = services.list_notifications(target2["id"], unread_only=True)
    assert any(n["id"] == notif_id for n in remaining)


def test_mark_notification_read_no_actor_id_allows():
    """Passing no actor_profile_id (e.g. system calls) skips ownership check."""
    services.create_profile("inviter3", role="admin")
    target3 = services.create_profile("notif_owner3", role="member")
    p = services.create_project("Notif Project 3", actor="inviter3")
    services.add_project_member(p["id"], "notif_owner3", actor="inviter3")

    notifs = services.list_notifications(target3["id"], unread_only=True)
    notif_id = notifs[0]["id"]

    result = services.mark_notification_read(notif_id, actor_profile_id=None)
    assert result is True


def test_mark_notification_read_nonexistent():
    result = services.mark_notification_read("doesnotexist")
    assert result is False
