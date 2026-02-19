"""Unit and integration tests for project membership auto-add on creation
and the assignee-scoping fix (list_project_members returns only project members).
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


# ── Auto-add creator as project member ───────────────────────────────────────

def test_creator_auto_added_as_member():
    """Non-system actor who creates a project must be auto-added as a member."""
    services.create_profile("alice", role="member")
    p = services.create_project("P", actor="alice")

    members = {m["name"] for m in services.list_project_members(p["id"])}
    assert "alice" in members


def test_system_actor_not_added_as_member():
    """'system' is not a real profile and must not appear in project members."""
    p = services.create_project("P", actor="system")
    assert services.list_project_members(p["id"]) == []


def test_creator_can_be_removed_after_auto_add():
    """Creator who was auto-added can subsequently be removed."""
    services.create_profile("alice", role="member")
    p = services.create_project("P", actor="alice")

    assert services.remove_project_member(p["id"], "alice") is True
    members = {m["name"] for m in services.list_project_members(p["id"])}
    assert "alice" not in members


def test_creator_not_duplicated_if_added_again():
    """Manually adding the creator again after auto-add must not create duplicates."""
    services.create_profile("alice", role="member")
    p = services.create_project("P", actor="alice")

    services.add_project_member(p["id"], "alice")  # second add — should be idempotent

    members = [m["name"] for m in services.list_project_members(p["id"])]
    assert members.count("alice") == 1


def test_multiple_projects_each_get_own_creator():
    services.create_profile("alice", role="member")
    services.create_profile("bob", role="member")

    p1 = services.create_project("P1", actor="alice")
    p2 = services.create_project("P2", actor="bob")

    p1_members = {m["name"] for m in services.list_project_members(p1["id"])}
    p2_members = {m["name"] for m in services.list_project_members(p2["id"])}

    assert p1_members == {"alice"}
    assert p2_members == {"bob"}


def test_unknown_actor_profile_gracefully_skipped():
    """If the actor profile doesn't exist in DB, project creation still succeeds."""
    p = services.create_project("P", actor="ghost_who_doesnt_exist")
    assert p["id"] is not None
    assert services.list_project_members(p["id"]) == []


# ── Assignee scoping (list_project_members) ───────────────────────────────────

def test_list_project_members_excludes_non_members():
    services.create_profile("alice", role="member")
    services.create_profile("bob", role="member")   # never added

    p = services.create_project("P")
    services.add_project_member(p["id"], "alice")

    members = {m["name"] for m in services.list_project_members(p["id"])}
    assert "alice" in members
    assert "bob" not in members


def test_list_project_members_scoped_per_project():
    services.create_profile("alice", role="member")
    services.create_profile("bob", role="member")

    p1 = services.create_project("P1")
    p2 = services.create_project("P2")
    services.add_project_member(p1["id"], "alice")
    services.add_project_member(p2["id"], "bob")

    assert {m["name"] for m in services.list_project_members(p1["id"])} == {"alice"}
    assert {m["name"] for m in services.list_project_members(p2["id"])} == {"bob"}


def test_removed_member_excluded_from_list():
    services.create_profile("alice", role="member")
    p = services.create_project("P")
    services.add_project_member(p["id"], "alice")
    services.remove_project_member(p["id"], "alice")

    assert not any(m["name"] == "alice" for m in services.list_project_members(p["id"]))


# ── Integration: full Bruno-style flow ───────────────────────────────────────

def test_creator_assigned_to_task_then_removed_from_project():
    """Mirrors the Bruno test flow: create project → assign task → remove creator."""
    services.create_profile("alice", role="member")
    p = services.create_project("P", actor="alice")

    # alice is now auto-member; assign task to her
    t = services.create_task(p["id"], "T", actor="system")
    services.update_task(t["id"], assignee="alice")

    # remove alice from project
    result = services.remove_project_member(p["id"], "alice")
    assert result is True

    # task should be unassigned
    assert services.get_task(t["id"])["assignee"] == ""
