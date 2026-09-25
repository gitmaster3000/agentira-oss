"""Loop v1 C3: the Conductor becomes a (visible) member of every project it
manages, so its MCP writes on that project are allowed."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.db import SessionLocal, privileged
from backend.forge import conductor, services as forge_services
from backend.models import Profile, ProjectMember
from backend.tests.test_conductor_turn_scopes import _mk_project_with_agent


@pytest.fixture(autouse=True)
def _db(pg):
    yield pg


def _conductor_memberships(project_id: str) -> int:
    with privileged(), SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == "Conductor").first()
        return (db.query(ProjectMember)
                  .filter(ProjectMember.project_id == project_id,
                          ProjectMember.profile_id == prof.id)
                  .count())


def _drop_conductor_membership(project_id: str) -> None:
    """New projects get their Conductor at creation; projects that predate
    that (e.g. Agentira Platform) don't — simulate one."""
    with privileged(), SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == "Conductor").first()
        (db.query(ProjectMember)
           .filter(ProjectMember.project_id == project_id,
                   ProjectMember.profile_id == prof.id)
           .delete())
        db.commit()


def test_planning_turn_adds_conductor_as_member_once():
    _, project_id, _ = _mk_project_with_agent("Mem")
    conductor.get_or_create_conductor()
    _drop_conductor_membership(project_id)
    assert _conductor_memberships(project_id) == 0
    with patch.object(forge_services, "send_runtime_message", return_value={"ok": True}), \
         patch.object(conductor, "_runtime_live", return_value=True), privileged():
        conductor.run_planning_turn()
        conductor.run_planning_turn()
    assert _conductor_memberships(project_id) == 1
