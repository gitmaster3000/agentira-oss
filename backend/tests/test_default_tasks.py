"""Default professionalization tasks — template load + project seeding.

The product ships a default backlog of "professionalization" epics (logging,
unit testing, integration testing, manual testing docs, security, CI/CD) that a
new project can seed and run with the Conductor. The backlog is stored as a
template (YAML), never hardcoded.
"""

from __future__ import annotations

import pytest

from backend import default_tasks
from backend import services as core_services
# Importing forge models registers their tables on Base.metadata.
from backend.forge import models as _forge_models  # noqa: F401


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg.SessionLocal


def test_load_default_tasks_parses_professionalization_backlog():
    tmpl = default_tasks.load_default_tasks()
    assert tmpl.name
    titles = " ".join(e.title.lower() for e in tmpl.epics)
    for area in ("logging", "unit", "integration", "manual", "security", "deploy"):
        assert area in titles, f"expected an epic covering {area!r}"
    # Every epic carries at least one task, and every task a DoD checklist.
    assert tmpl.epics
    for epic in tmpl.epics:
        assert epic.tasks, f"epic {epic.title!r} has no tasks"
        for task in epic.tasks:
            assert task.title and task.description
            assert task.dod, f"task {task.title!r} has no DoD items"


def test_integration_epic_defaults_to_bruno():
    tmpl = default_tasks.load_default_tasks()
    integ = next(e for e in tmpl.epics if "integration" in e.title.lower())
    blob = (integ.description + " " + " ".join(
        t.description for t in integ.tasks)).lower()
    assert "bruno" in blob, "integration testing must default to Bruno"


def test_seed_default_tasks_creates_epics_and_tasks():
    proj = core_services.create_project(
        "Prof proj", actor="system", initial_tasks=[], members=[])
    summary = default_tasks.seed_default_tasks(proj["id"], actor="system")

    tmpl = default_tasks.load_default_tasks()
    epics = core_services.list_epics(proj["id"], actor="system")
    assert {e["title"] for e in epics} == {e.title for e in tmpl.epics}
    assert summary["epics_created"] == len(tmpl.epics)

    # Tasks are attached under their epic, in backlog, with DoD + descriptions.
    total_tasks = 0
    for tmpl_epic in tmpl.epics:
        epic_row = next(e for e in epics if e["title"] == tmpl_epic.title)
        rows = core_services.list_epic_tasks(epic_row["id"])
        assert {r["title"] for r in rows} == {t.title for t in tmpl_epic.tasks}
        for r in rows:
            assert r["status"] == "backlog"
            assert r["description"]
            assert r["dod_items"]
        total_tasks += len(rows)
    assert summary["tasks_created"] == total_tasks


def test_create_project_with_seed_defaults_seeds_backlog():
    """create_project(seed_defaults=True) materializes the default backlog
    alongside the wizard's own initial tasks."""
    proj = core_services.create_project(
        "Seeded proj", actor="system",
        initial_tasks=[{"title": "Custom kickoff"}], members=[],
        seed_defaults=True,
    )
    tmpl = default_tasks.load_default_tasks()
    epics = core_services.list_epics(proj["id"], actor="system")
    assert {e["title"] for e in epics} == {e.title for e in tmpl.epics}
    titles = {t["title"] for t in core_services.list_tasks(proj["id"], actor="system")}
    assert "Custom kickoff" in titles


def test_create_project_without_seed_defaults_seeds_nothing():
    proj = core_services.create_project(
        "Unseeded proj", actor="system", initial_tasks=[], members=[])
    assert core_services.list_epics(proj["id"], actor="system") == []


def test_seed_default_tasks_is_idempotent():
    proj = core_services.create_project(
        "Idempotent proj", actor="system", initial_tasks=[], members=[])
    default_tasks.seed_default_tasks(proj["id"], actor="system")
    second = default_tasks.seed_default_tasks(proj["id"], actor="system")

    assert second["epics_created"] == 0
    assert second["tasks_created"] == 0
    # No duplicate epics created on the re-run.
    tmpl = default_tasks.load_default_tasks()
    epics = core_services.list_epics(proj["id"], actor="system")
    assert len(epics) == len(tmpl.epics)
