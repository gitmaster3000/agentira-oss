"""AP-153: project creation wizard payload.

`create_project(initial_tasks=..., members=...)` lets the wizard own
membership + initial-task bodies. Legacy callers (initial_tasks=None,
members=None) still get the auto-seed (Conductor + empty "Plan this
project" task).
"""

from __future__ import annotations

import pytest

from backend import services as core_services
# Importing forge models registers their tables on `Base.metadata`.
from backend.forge import models as _forge_models  # noqa: F401
from backend.models import Profile, Task, ProjectMember


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg.SessionLocal


def _query(TestSession, model, **kw):
    with TestSession() as db:
        return db.query(model).filter_by(**kw).all()


def test_legacy_create_still_auto_seeds_conductor_and_kickoff(test_db):
    """No wizard payload → current behavior: Conductor + empty kickoff task."""
    p = core_services.create_project("Legacy proj", actor="system")
    tasks = _query(test_db, Task, project_id=p["id"])
    assert len(tasks) == 1
    assert tasks[0].title == "Plan this project"
    assert tasks[0].assignee == "Conductor"
    assert tasks[0].description == ""
    # Conductor is a member.
    with test_db() as db:
        cond = db.query(Profile).filter_by(name="Conductor").first()
        assert cond is not None
        members = db.query(ProjectMember).filter_by(project_id=p["id"]).all()
        assert any(m.profile_id == cond.id for m in members)


def test_wizard_payload_skips_auto_seed_uses_initial_tasks(test_db):
    """Wizard payload → use it verbatim; no Conductor auto-add, no
    "Plan this project" auto-task. Empty list of members means the user
    deliberately chose no agents."""
    p = core_services.create_project(
        "Wizard proj", actor="system",
        initial_tasks=[
            {"title": "Plan the auth flow",
             "description": "Use Auth0. Output a one-page plan.",
             "assignee": "", "priority": "high"},
            {"title": "Set up CI/CD",
             "description": "GitHub Actions, deploy to Fly.",
             "priority": "medium"},
        ],
        members=[],
    )
    tasks = _query(test_db, Task, project_id=p["id"])
    titles = {t.title for t in tasks}
    assert titles == {"Plan the auth flow", "Set up CI/CD"}
    # User-supplied descriptions land verbatim — no code constants involved.
    bodies = {t.title: t.description for t in tasks}
    assert "Auth0" in bodies["Plan the auth flow"]
    assert "GitHub Actions" in bodies["Set up CI/CD"]

    # No Conductor auto-added — and indeed the Conductor profile was
    # never even seeded since the wizard path didn't trigger it.
    with test_db() as db:
        member_profile_names = set()
        for m in db.query(ProjectMember).filter_by(project_id=p["id"]).all():
            prof = db.get(Profile, m.profile_id)
            if prof:
                member_profile_names.add(prof.name)
        assert "Conductor" not in member_profile_names


def test_wizard_payload_with_members_adds_them(test_db):
    """Wizard explicitly lists members → they get added; Conductor only
    if listed."""
    # Conductor is a workspace singleton — ensure it's seeded before the
    # wizard tries to add it. In a real workspace it's seeded on first
    # project create (legacy path) or first daemon registration.
    from backend.forge.conductor import get_or_create_conductor
    get_or_create_conductor()

    core_services.create_profile("backend-dev", role="member")
    p = core_services.create_project(
        "Wizard with members", actor="system",
        initial_tasks=[{"title": "Start something"}],
        members=["Conductor", "backend-dev"],
    )
    with test_db() as db:
        member_rows = db.query(ProjectMember).filter_by(project_id=p["id"]).all()
        member_names = set()
        for m in member_rows:
            prof = db.get(Profile, m.profile_id)
            if prof:
                member_names.add(prof.name)
        assert {"Conductor", "backend-dev"} <= member_names


def test_wizard_empty_initial_tasks_creates_no_tasks(test_db):
    """`initial_tasks=[]` is a legitimate choice — "I'll add tasks later."
    Distinct from None (which means legacy auto-seed)."""
    p = core_services.create_project(
        "Empty tasks proj", actor="system",
        initial_tasks=[], members=[],
    )
    tasks = _query(test_db, Task, project_id=p["id"])
    assert tasks == []
