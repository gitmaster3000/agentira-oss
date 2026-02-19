"""Tests for assignee scoping — project members only, not all profiles.

These tests verify the backend contract that the frontend fix depends on:
list_project_members must return only members of that specific project,
not every profile in the system.
"""

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


# ── Unit: list_project_members scoping ───────────────────────────────────────

def test_project_members_empty_by_default():
    """A new project has no members."""
    p = services.create_project("P")
    assert services.list_project_members(p["id"]) == []


def test_project_members_only_includes_added_members():
    """Profiles that were never added to the project must not appear."""
    services.create_profile("alice", role="member")
    services.create_profile("bob", role="member")
    services.create_profile("carol", role="member")  # never added

    p = services.create_project("P")
    services.add_project_member(p["id"], "alice")
    services.add_project_member(p["id"], "bob")

    members = services.list_project_members(p["id"])
    names = {m["name"] for m in members}

    assert "alice" in names
    assert "bob" in names
    assert "carol" not in names  # key assertion: not a member, must be excluded


def test_non_member_profiles_excluded_even_with_many_users():
    """Regression: global profile list must never bleed into project member list."""
    for i in range(10):
        services.create_profile(f"user{i}", role="member")

    p = services.create_project("P")
    services.add_project_member(p["id"], "user0")
    services.add_project_member(p["id"], "user1")

    members = services.list_project_members(p["id"])
    assert len(members) == 2
    names = {m["name"] for m in members}
    assert names == {"user0", "user1"}


def test_members_scoped_per_project():
    """Members of project A must not appear in project B's member list."""
    services.create_profile("alice", role="member")
    services.create_profile("bob", role="member")

    p1 = services.create_project("P1")
    p2 = services.create_project("P2")

    services.add_project_member(p1["id"], "alice")
    services.add_project_member(p2["id"], "bob")

    p1_members = {m["name"] for m in services.list_project_members(p1["id"])}
    p2_members = {m["name"] for m in services.list_project_members(p2["id"])}

    assert p1_members == {"alice"}
    assert p2_members == {"bob"}


def test_removed_member_no_longer_in_list():
    services.create_profile("alice", role="member")
    p = services.create_project("P")
    services.add_project_member(p["id"], "alice")

    assert any(m["name"] == "alice" for m in services.list_project_members(p["id"]))

    services.remove_project_member(p["id"], "alice")

    assert not any(m["name"] == "alice" for m in services.list_project_members(p["id"]))


def test_list_project_members_unknown_project_returns_empty():
    result = services.list_project_members("nonexistent-id")
    assert result == []


# ── Integration: task assignee must be a project member ───────────────────────

def test_task_assignee_is_a_project_member():
    """The assigned user on a task should always be in the project member list."""
    services.create_profile("boss", role="admin")
    services.create_profile("worker", role="member")

    p = services.create_project("P", actor="boss")
    services.add_project_member(p["id"], "worker", actor="boss")

    t = services.create_task(p["id"], "T", assignee="worker", actor="boss")

    member_names = {m["name"] for m in services.list_project_members(p["id"])}
    assert t["assignee"] in member_names


def test_member_list_reflects_current_membership_state():
    """Member list must be consistent after add/remove cycles."""
    for name in ("alice", "bob", "carol"):
        services.create_profile(name, role="member")

    p = services.create_project("P")
    services.add_project_member(p["id"], "alice")
    services.add_project_member(p["id"], "bob")
    services.add_project_member(p["id"], "carol")
    services.remove_project_member(p["id"], "bob")

    names = {m["name"] for m in services.list_project_members(p["id"])}
    assert names == {"alice", "carol"}
    assert "bob" not in names
