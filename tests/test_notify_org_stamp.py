"""Regression: forge notification helpers must stamp org_id explicitly.

The conductor tick / scheduler run in a background thread with NO request org
context, so the before_flush org-stamping hook can't fill org_id. Before the
fix, every background dispatch died on `notifications.org_id` NOT NULL and the
whole run-creation transaction rolled back (prod incident 2026-07-04).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base, set_current_org
from backend.models import Profile, Project, ProjectMember, Notification, Role
from backend.forge import services as forge_services

from tests.conftest import SYSTEM_ORG_ID


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = TestSession()
    yield db
    db.close()


def _seed_member(db):
    """A project with one member, created under the normal org context."""
    prof = Profile(name="member-1", account_type="human")
    proj = Project(name="P")
    db.add_all([prof, proj])
    db.flush()
    db.add(ProjectMember(project_id=proj.id, profile_id=prof.id))
    db.flush()
    return prof, proj


def test_notify_project_members_stamps_org_without_context(db_session):
    prof, proj = _seed_member(db_session)
    # Simulate the background scheduler thread: no org context at all.
    set_current_org(None)
    with patch("backend.notifications.broker.notify"):
        forge_services._notify_project_members(
            db_session, project_id=proj.id, type_="forge.run.created",
            title="run created", link="/forge/runs/x")
        db_session.commit()  # NOT NULL violation here before the fix
    rows = db_session.query(Notification).all()
    assert len(rows) == 1
    assert rows[0].org_id == SYSTEM_ORG_ID
    assert rows[0].profile_id == prof.id


def test_notify_admins_stamps_org_without_context(db_session):
    role = Role(name="admin")
    prof = Profile(name="admin-1", account_type="human")
    prof.roles.append(role)
    db_session.add_all([role, prof])
    db_session.flush()
    set_current_org(None)
    forge_services._notify_admins(
        db_session, type_="forge.run.failed", title="run failed", link="/x")
    db_session.commit()
    rows = db_session.query(Notification).all()
    assert len(rows) == 1
    assert rows[0].org_id == SYSTEM_ORG_ID
