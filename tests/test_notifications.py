"""Tests for Unified Audit & Notification system."""

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

def test_project_audit_trail():
    services.create_profile("admin", role="admin")
    p = services.create_project("Audit Project", actor="admin")
    
    # Check activity record
    with services._session() as db:
        activities = services.get_activity(None) # Generic fetch? No, need project fetch
        # Project.activities
        proj = db.get(services.Project, p["id"])
        assert len(proj.activities) == 1
        assert proj.activities[0].action == "project.create"

def test_notification_dispatch_on_invite():
    services.create_profile("adder", role="admin")
    target = services.create_profile("target", role="member")
    p = services.create_project("Invite Project", actor="adder")
    
    # Add member -> trigger notification
    services.add_project_member(p["id"], "target", actor="adder")
    
    notifs = services.list_notifications(target["id"])
    assert len(notifs) >= 1
    assert any("project.member.add" in n["type"] for n in notifs)

def test_task_assignment_notification():
    services.create_profile("boss", role="admin")
    worker = services.create_profile("worker", role="member")
    p = services.create_project("Work", actor="boss")
    services.add_project_member(p["id"], "worker", actor="boss")
    
    # Create task assigned to worker
    services.create_task(p["id"], "Do it", assignee="worker", actor="boss")
    
    notifs = services.list_notifications(worker["id"])
    # Expected: member.add + task.create
    types = [n["type"] for n in notifs]
    assert "task.create" in types
