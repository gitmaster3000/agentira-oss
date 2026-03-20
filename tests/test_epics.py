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
        db = TestSession()
        services._seed_defaults(db)
        db.close()
        yield TestSession


def test_epic_crud_fields(test_db):
    """Full CRUD with field validation."""
    project = services.create_project("Epic Project", actor="system")
    pid = project["id"]

    # Create
    epic = services.create_epic(pid, title="First Epic", description="My description", color="#123456", actor="system")
    assert epic["title"] == "First Epic"
    assert epic["description"] == "My description"
    assert epic["color"] == "#123456"
    assert epic["status"] == "backlog"
    assert epic["project_id"] == pid
    assert epic["task_count"] == 0
    assert "id" in epic
    assert "created_at" in epic

    epic_id = epic["id"]

    # List
    epics = services.list_epics(pid)
    assert len(epics) == 1
    assert epics[0]["id"] == epic_id
    assert epics[0]["task_count"] == 0

    # Update - partial
    updated = services.update_epic(epic_id, title="Updated Epic", actor="system")
    assert updated["title"] == "Updated Epic"
    assert updated["color"] == "#123456"  # unchanged

    # Update - color only
    updated = services.update_epic(epic_id, color="#654321", actor="system")
    assert updated["title"] == "Updated Epic"  # unchanged
    assert updated["color"] == "#654321"

    # Delete
    assert services.delete_epic(epic_id) is True
    assert services.list_epics(pid) == []

    # Delete nonexistent
    assert services.delete_epic("nonexistent") is False


def test_epic_default_color(test_db):
    """Epic gets default color if not specified."""
    project = services.create_project("Color Test", actor="system")
    epic = services.create_epic(project["id"], title="No Color", actor="system")
    assert epic["color"] == "#7c4dff"


def test_epic_invalid_project(test_db):
    """Creating epic with invalid project raises."""
    with pytest.raises(ValueError, match="not found"):
        services.create_epic("nonexistent", title="Bad", actor="system")


def test_update_nonexistent_epic(test_db):
    """Updating nonexistent epic raises."""
    with pytest.raises(ValueError, match="not found"):
        services.update_epic("nonexistent", title="Bad", actor="system")


def test_epic_task_assignment(test_db):
    """Task epic_id links correctly, shows in task dict."""
    project = services.create_project("Link Test", actor="system")
    pid = project["id"]

    epic = services.create_epic(pid, title="Feature X", color="#ff0000", actor="system")
    eid = epic["id"]

    t = services.create_task(pid, "Linked Task", epic_id=eid, actor="system")
    assert t["epic_id"] == eid
    assert t["epic_name"] == "Feature X"
    assert t["epic_color"] == "#ff0000"

    # Unlinked task
    t2 = services.create_task(pid, "Free Task", actor="system")
    assert t2["epic_id"] is None
    assert t2["epic_name"] is None
    assert t2["epic_color"] is None


def test_epic_task_count_updates(test_db):
    """Task count changes as tasks are assigned/unassigned."""
    project = services.create_project("Count Test", actor="system")
    pid = project["id"]
    epic = services.create_epic(pid, title="Counter", actor="system")
    eid = epic["id"]

    t1 = services.create_task(pid, "T1", epic_id=eid, actor="system")
    t2 = services.create_task(pid, "T2", epic_id=eid, actor="system")
    assert services.list_epics(pid)[0]["task_count"] == 2

    # Unassign
    services.update_task(t1["id"], epic_id="", actor="system")
    assert services.list_epics(pid)[0]["task_count"] == 1


def test_delete_epic_unlinks_tasks(test_db):
    """Deleting an epic sets epic_id to None on linked tasks."""
    project = services.create_project("Unlink Test", actor="system")
    pid = project["id"]
    epic = services.create_epic(pid, title="Doomed", actor="system")
    eid = epic["id"]

    t = services.create_task(pid, "Orphan Soon", epic_id=eid, actor="system")
    assert t["epic_id"] == eid

    services.delete_epic(eid)
    refreshed = services.get_task(t["id"])
    assert refreshed["epic_id"] is None
    assert refreshed["epic_name"] is None


def test_roadmap_by_epic(test_db):
    """Roadmap groups tasks by epic with correct structure."""
    project = services.create_project("Roadmap Project", actor="system")
    pid = project["id"]

    epic = services.create_epic(pid, title="Feature X", actor="system")
    eid = epic["id"]

    services.create_task(pid, "Task 1", tags=["backend"], epic_id=eid, actor="system")
    services.create_task(pid, "Task 2", tags=["frontend"], epic_id=eid, actor="system")
    services.create_task(pid, "Task 3", tags=["backend"], actor="system")

    roadmap = services.get_roadmap(pid, group_by="epic")
    assert roadmap["summary"]["total_tasks"] == 3
    assert roadmap["summary"]["total_epics"] == 2  # Feature X + Ungrouped
    assert roadmap["project"]["id"] == pid
    assert roadmap["project"]["name"] == "Roadmap Project"
    assert isinstance(roadmap["milestones"], list)

    groups = {g["name"]: g for g in roadmap["epics"]}
    assert "Feature X" in groups
    assert "Ungrouped" in groups
    assert groups["Feature X"]["total"] == 2
    assert groups["Feature X"]["done"] == 0
    assert groups["Ungrouped"]["total"] == 1

    # Tasks have key field
    for g in roadmap["epics"]:
        for t in g["tasks"]:
            assert "key" in t
            assert "id" in t
            assert "status" in t
            assert "priority" in t


def test_roadmap_by_tag(test_db):
    """Roadmap groups by first tag."""
    project = services.create_project("Tag Roadmap", actor="system")
    pid = project["id"]

    services.create_task(pid, "T1", tags=["api", "v2"], actor="system")
    services.create_task(pid, "T2", tags=["api"], actor="system")
    services.create_task(pid, "T3", tags=["ui"], actor="system")

    roadmap = services.get_roadmap(pid, group_by="tag")
    tag_groups = {g["name"]: g for g in roadmap["epics"]}
    assert "api" in tag_groups
    assert "ui" in tag_groups
    assert tag_groups["api"]["total"] == 2
    assert tag_groups["ui"]["total"] == 1


def test_roadmap_empty_project(test_db):
    """Roadmap on empty project returns zero counts."""
    project = services.create_project("Empty", actor="system")
    roadmap = services.get_roadmap(project["id"])
    assert roadmap["summary"]["total_tasks"] == 0
    assert roadmap["summary"]["total_epics"] == 0
    assert roadmap["epics"] == []
    assert roadmap["milestones"] == []


def test_multiple_epics_per_project(test_db):
    """Multiple epics in same project listed correctly."""
    project = services.create_project("Multi Epic", actor="system")
    pid = project["id"]

    e1 = services.create_epic(pid, title="Epic A", color="#111111", actor="system")
    e2 = services.create_epic(pid, title="Epic B", color="#222222", actor="system")
    e3 = services.create_epic(pid, title="Epic C", color="#333333", actor="system")

    epics = services.list_epics(pid)
    assert len(epics) == 3
    titles = {e["title"] for e in epics}
    assert titles == {"Epic A", "Epic B", "Epic C"}
