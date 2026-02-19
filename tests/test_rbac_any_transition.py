"""Tests for transition:* wildcard permission (any-to-any task moves)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend.models import Role, Permission, RolePermission
from backend import services
from backend.auth import check_transition, has_permission


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


# ── Unit: permission seeding ──────────────────────────────────────────────────

def test_transition_wildcard_permission_exists():
    """transition:* must be seeded in the permissions table."""
    with services._session() as db:
        perm = db.query(Permission).filter(Permission.codename == "transition:*").first()
    assert perm is not None


def test_transition_wildcard_granted_to_member():
    with services._session() as db:
        assert has_permission(db, "member_user", "transition:*") is False  # profile doesn't exist yet
        services.create_profile("member_user", role="member")
    with services._session() as db:
        assert has_permission(db, "member_user", "transition:*") is True


def test_transition_wildcard_granted_to_bot():
    services.create_profile("bot_user", role="bot")
    with services._session() as db:
        assert has_permission(db, "bot_user", "transition:*") is True


def test_transition_wildcard_granted_to_admin():
    services.create_profile("admin_user", role="admin")
    with services._session() as db:
        assert has_permission(db, "admin_user", "transition:*") is True


def test_viewer_does_not_have_transition_wildcard():
    services.create_profile("viewer_user", role="viewer")
    with services._session() as db:
        assert has_permission(db, "viewer_user", "transition:*") is False


# ── Unit: check_transition logic ──────────────────────────────────────────────

def test_check_transition_same_status_always_passes():
    """Moving to the same status is a no-op and must never raise."""
    services.create_profile("viewer_user", role="viewer")
    with services._session() as db:
        check_transition(db, "viewer_user", "todo", "todo")  # must not raise


def test_check_transition_member_any_direction():
    """Member with transition:* can move in any direction."""
    services.create_profile("alice", role="member")
    with services._session() as db:
        check_transition(db, "alice", "done", "todo")
        check_transition(db, "alice", "done", "backlog")
        check_transition(db, "alice", "review", "todo")
        check_transition(db, "alice", "in_progress", "todo")


def test_check_transition_viewer_blocked():
    """Viewer must still be blocked from all transitions."""
    services.create_profile("viewer", role="viewer")
    with services._session() as db:
        with pytest.raises(PermissionError):
            check_transition(db, "viewer", "backlog", "todo")


def test_check_transition_unknown_actor_blocked():
    """Unknown actor (no profile) must be denied."""
    with services._session() as db:
        with pytest.raises(PermissionError):
            check_transition(db, "ghost", "backlog", "todo")


# ── Integration: full task move flow ─────────────────────────────────────────

def test_member_can_move_task_backwards():
    """Member can move a task from done back to todo via service layer."""
    services.create_profile("alice", role="member")
    p = services.create_project("P")
    t = services.create_task(p["id"], "T", actor="system")

    services.move_task(t["id"], "done", actor="system")
    assert services.get_task(t["id"])["status"] == "done"

    moved = services.move_task(t["id"], "todo", actor="alice")
    assert moved["status"] == "todo"


def test_bot_can_move_task_any_direction():
    services.create_profile("bot", role="bot")
    p = services.create_project("P")
    t = services.create_task(p["id"], "T", actor="system")

    services.move_task(t["id"], "review", actor="system")
    moved = services.move_task(t["id"], "backlog", actor="bot")
    assert moved["status"] == "backlog"


def test_viewer_move_raises_permission_error():
    services.create_profile("viewer", role="viewer")
    p = services.create_project("P")
    t = services.create_task(p["id"], "T", actor="system")
    with pytest.raises(PermissionError):
        services.move_task(t["id"], "todo", actor="viewer")


def test_move_activity_logged_with_diff():
    """Moving a task must record a structured diff in the activity log."""
    services.create_profile("alice", role="member")
    p = services.create_project("P")
    t = services.create_task(p["id"], "T", actor="system")

    services.move_task(t["id"], "done", actor="system")
    services.move_task(t["id"], "todo", actor="alice")

    activities = services.get_activity(t["id"])
    move_acts = [a for a in activities if a["action"] == "task.move" and a["actor"] == "alice"]
    assert len(move_acts) == 1
    diff = move_acts[0]["diff"]
    assert diff is not None
    assert diff["status"]["from"] == "done"
    assert diff["status"]["to"] == "todo"
