"""Unit tests for AgentIRA Epic services."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend import services

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

def test_epic_crud(test_db):
    project = services.create_project("Epic Project", actor="system")
    pid = project["id"]

    # Create epic
    epic = services.create_epic(pid, title="First Epic", description="My description", color="#123456", actor="system")
    assert epic["title"] == "First Epic"
    assert epic["description"] == "My description"
    assert epic["color"] == "#123456"

    epic_id = epic["id"]

    # List epics
    epics = services.list_epics(pid)
    assert len(epics) == 1
    assert epics[0]["id"] == epic_id
    assert epics[0]["task_count"] == 0

    # Update epic
    updated = services.update_epic(epic_id, title="Updated Epic", color="#654321", actor="system")
    assert updated["title"] == "Updated Epic"
    assert updated["color"] == "#654321"

    # Delete epic
    res = services.delete_epic(epic_id)
    assert res is True
    epics = services.list_epics(pid)
    assert len(epics) == 0

def test_epic_task_assignment_and_roadmap(test_db):
    project = services.create_project("Roadmap Project", actor="system")
    pid = project["id"]

    epic = services.create_epic(pid, title="Feature X", actor="system")
    epic_id = epic["id"]

    # Create tasks
    t1 = services.create_task(pid, "Task 1", tags=["backend"], epic_id=epic_id, actor="system")
    t2 = services.create_task(pid, "Task 2", tags=["frontend"], epic_id=epic_id, actor="system")
    t3 = services.create_task(pid, "Task 3", tags=["backend"], actor="system")

    # Epic task count
    epics = services.list_epics(pid)
    assert epics[0]["task_count"] == 2

    # Roadmap by epic
    roadmap_epic = services.get_roadmap(pid, group_by="epic")
    assert roadmap_epic["summary"]["total_epics"] == 2 # 1 epic + Ungrouped
    
    # Check groups
    groups = {g["name"]: g for g in roadmap_epic["epics"]}
    assert "Feature X" in groups
    assert "Ungrouped" in groups
    assert groups["Feature X"]["total"] == 2
    assert groups["Ungrouped"]["total"] == 1

    # Roadmap by tag
    roadmap_tag = services.get_roadmap(pid, group_by="tag")
    # tags are: backend, frontend, No Tag
    tag_groups = {g["name"]: g for g in roadmap_tag["epics"]}
    assert "backend" in tag_groups
    assert "frontend" in tag_groups
    assert tag_groups["backend"]["total"] == 2
    assert tag_groups["frontend"]["total"] == 1

    # Unassign epic via update
    services.update_task(t1["id"], epic_id="", actor="system")
    epics = services.list_epics(pid)
    assert epics[0]["task_count"] == 1
