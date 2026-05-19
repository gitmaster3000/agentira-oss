"""Unit tests for AgentIRA service layer."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend import services
# Register the forge tables on Base.metadata so create_all can resolve
# the profiles.runtime_id → forge_runtimes FK even when this file runs
# on its own (not just alongside tests that import forge models).
import backend.forge.models  # noqa: F401

@pytest.fixture(autouse=True)
def test_db():
    """Create an in-memory SQLite DB and patch SessionLocal for every test."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with patch("backend.services.SessionLocal", TestSession):
        # Seed defaults
        db = TestSession()
        services._seed_defaults(db)
        db.close()
        yield TestSession

def test_remove_project_member_clears_task_assignments():
    """
    Test that removing a member from a project clears assignments 
    for all tasks in that project assigned to them.
    """
    # 1. Setup project and profiles
    p = services.create_project("Test Project")
    services.create_profile("alice", role="member")
    services.create_profile("bob", role="member")
    
    services.add_project_member(p["id"], "alice")
    services.add_project_member(p["id"], "bob")
    
    # 2. Setup tasks
    t1 = services.create_task(p["id"], "Alice's Task", actor="system")
    services.update_task(t1["id"], assignee="alice")
    
    t2 = services.create_task(p["id"], "Bob's Task", actor="system")
    services.update_task(t2["id"], assignee="bob")
    
    t3 = services.create_task(p["id"], "Shared Task", actor="system")
    services.update_task(t3["id"], assignee="alice")
    
    # 3. Verify initial state
    assert services.get_task(t1["id"])["assignee"] == "alice"
    assert services.get_task(t2["id"])["assignee"] == "bob"
    assert services.get_task(t3["id"])["assignee"] == "alice"
    
    # 4. Trigger removal
    services.remove_project_member(p["id"], "alice")
    
    # 5. Validation
    # Alice's tasks should be unassigned
    assert services.get_task(t1["id"])["assignee"] == ""
    assert services.get_task(t3["id"])["assignee"] == ""
    
    # Bob's task should remain assigned
    assert services.get_task(t2["id"])["assignee"] == "bob"
    
    # Verify activity was logged
    activities = services.get_activity(t1["id"])
    assert any(a["action"] == "task.unassign" for a in activities)
    
    # Verify alice is no longer a member
    p_updated = services.get_project(p["id"])
    assert "alice" not in p_updated["members"]
    assert "bob" in p_updated["members"]


def test_create_task_with_dates(test_db):
    from backend import services, models
    project = services.create_project("Dates Project", "Desc", actor="system")
    
    task = services.create_task(
        project["id"],
        "Task with dates",
        start_date="2026-04-01T00:00:00Z",
        due_date="2026-04-15T00:00:00Z",
        actor="system"
    )
    
    assert "start_date" in task
    assert "due_date" in task
    assert task["start_date"].startswith("2026-04-01")
    assert task["due_date"].startswith("2026-04-15")

def test_update_task_dates(test_db):
    from backend import services
    project = services.create_project("Update Dates", "Desc", actor="system")
    task = services.create_task(project["id"], "Initial task", actor="system")
    
    updated = services.update_task(
        task["id"],
        start_date="2026-05-01T00:00:00Z",
        due_date="2026-05-10T00:00:00Z",
        actor="system"
    )
    assert updated["start_date"].startswith("2026-05-01")
    assert updated["due_date"].startswith("2026-05-10")

def test_get_roadmap(test_db):
    from backend import services
    project = services.create_project("Roadmap Proj", "Desc", actor="system")
    services.create_task(
        project["id"], "R1", start_date="2026-06-01T00:00:00Z", due_date="2026-06-15T00:00:00Z", actor="system"
    )
    
    roadmap = services.get_roadmap(project["id"])
    # get_roadmap returns a structured dict: {project, epics, milestones,
    # summary}. The one task has no epic → a single "Ungrouped" group.
    assert roadmap["summary"]["total_tasks"] == 1
    assert len(roadmap["epics"]) == 1
    task = roadmap["epics"][0]["tasks"][0]
    assert task["title"] == "R1"
    assert task["start"].startswith("2026-06-01")
    assert task["end"].startswith("2026-06-15")
