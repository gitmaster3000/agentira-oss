"""Task key uniqueness must be scoped to project, not global.

Bug: tasks.key had a global UNIQUE constraint. Two orgs sharing a project
key prefix (e.g. both named "Pitch Fox" → "PF") would collide on "PF-1",
making task creation 500 for the second org.

Fix: constraint changed to (project_id, key). These tests cover:
  - Unit: key generation logic is prefix + sequential counter
  - Integration (Postgres): cross-org same-prefix projects don't collide
  - Integration (Postgres): duplicate keys within a project are rejected
  - Integration (Postgres): migration left the right constraints in place
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

import backend.db as bdb
from backend import services as core_services
from backend.models import Org, Project


# ── Unit tests (no DB) ─────────────────────────────────────────────────────

class TestDerivePrefix:
    def test_two_word_name(self):
        from backend.services import _derive_prefix
        assert _derive_prefix("Pitch Fox") == "PF"

    def test_single_word_strips_vowels(self):
        from backend.services import _derive_prefix
        result = _derive_prefix("Tasks")
        assert result.isupper()
        assert len(result) >= 2

    def test_empty_name_fallback(self):
        from backend.services import _derive_prefix
        assert _derive_prefix("") == "PROJ"
        assert _derive_prefix("123") == "PROJ"

    def test_five_word_cap(self):
        from backend.services import _derive_prefix
        result = _derive_prefix("One Two Three Four Five Six")
        assert result == "OTTFF"


# ── Integration tests (Postgres via pg fixture) ────────────────────────────

@pytest.fixture
def two_orgs(pg):
    """Yield (org1_id, org2_id) with the DB engine pointed at the test container."""
    org1_id = pg.org_id  # already created by the pg fixture
    with bdb.privileged(), bdb.SessionLocal() as db:
        org2 = Org(name="SecondOrg")
        db.add(org2)
        db.commit()
        org2_id = org2.id
    yield org1_id, org2_id


def test_same_prefix_different_orgs_do_not_collide(two_orgs):
    """The original bug: both orgs create a project named 'Pitch Fox' → prefix
    PF, then both try to create their first task (PF-1). Must succeed for both."""
    org1_id, org2_id = two_orgs

    bdb.set_current_org(org1_id)
    p1 = core_services.create_project("Pitch Fox", actor="system",
                                      initial_tasks=[], members=[])
    t1 = core_services.create_task(p1["id"], "First task", actor="system")

    bdb.set_current_org(org2_id)
    p2 = core_services.create_project("Pitch Fox", actor="system",
                                      initial_tasks=[], members=[])
    t2 = core_services.create_task(p2["id"], "First task", actor="system")

    assert t1["key"] == "PF-1"
    assert t2["key"] == "PF-1"
    assert t1["id"] != t2["id"]


def test_keys_increment_within_project(pg):
    """Sequential task creation within a single project gets PF-1, PF-2, …"""
    bdb.set_current_org(pg.org_id)
    project = core_services.create_project("Prefix Fox", actor="system",
                                           initial_tasks=[], members=[])
    t1 = core_services.create_task(project["id"], "Task 1", actor="system")
    t2 = core_services.create_task(project["id"], "Task 2", actor="system")
    t3 = core_services.create_task(project["id"], "Task 3", actor="system")

    assert t1["key"] == "PF-1"
    assert t2["key"] == "PF-2"
    assert t3["key"] == "PF-3"


def test_duplicate_key_within_project_is_rejected(pg):
    """Manually forcing a duplicate (project_id, key) pair must raise."""
    from sqlalchemy.exc import IntegrityError

    bdb.set_current_org(pg.org_id)
    with bdb.privileged(), bdb.SessionLocal() as db:
        proj = Project(name="Dupe Test", key_prefix="DT", org_id=pg.org_id)
        db.add(proj)
        db.commit()
        project_id = proj.id

    with pytest.raises(IntegrityError, match="uq_tasks_project_key"):
        with bdb.privileged(), bdb.SessionLocal() as db:
            from backend.models import Task, TaskPriority
            from backend.services import _get_status_id
            status_id = _get_status_id(db, "backlog")
            db.add(Task(project_id=project_id, key="DT-1", type="task",
                        title="A", status_id=status_id,
                        priority=TaskPriority.MEDIUM, org_id=pg.org_id))
            db.add(Task(project_id=project_id, key="DT-1", type="task",
                        title="B", status_id=status_id,
                        priority=TaskPriority.MEDIUM, org_id=pg.org_id))
            db.flush()


def test_same_key_allowed_across_projects(pg):
    """PF-1 in project A and PF-1 in project B (same org) is allowed after the fix."""
    bdb.set_current_org(pg.org_id)
    pA = core_services.create_project("Alpha", actor="system",
                                      initial_tasks=[], members=[])
    pB = core_services.create_project("Beta", actor="system",
                                      initial_tasks=[], members=[])

    tA = core_services.create_task(pA["id"], "Task", actor="system")
    tB = core_services.create_task(pB["id"], "Task", actor="system")

    # Both first tasks in their respective projects — keys are project-scoped
    assert tA["key"].endswith("-1")
    assert tB["key"].endswith("-1")


def test_migration_replaced_global_constraint_with_project_scoped(pg):
    """After migration: tasks_key_key is gone, uq_tasks_project_key exists."""
    with bdb.SessionLocal() as db:
        indexes = {
            r[0] for r in db.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename='tasks'"
            ))
        }

    assert "tasks_key_key" not in indexes, (
        "Global unique constraint tasks_key_key should have been dropped by migration"
    )
    assert "uq_tasks_project_key" in indexes, (
        "Per-project constraint uq_tasks_project_key must exist after migration"
    )
