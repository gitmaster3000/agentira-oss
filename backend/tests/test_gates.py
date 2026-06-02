"""AP-158: column-exit gates on task transitions.

Pure-ish checkers (each gate reads task fields, returns ok/reason) +
the engine that runs them on a transition + the wire-up in `move_task`
that blocks the move with a structured GateFailure when the project
opted in via `gates_enabled`.
"""

from __future__ import annotations

import json as _json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services  # noqa: F401 — mappers
from backend.models import Project, Task
from backend import gates


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.conductor.SessionLocal", TestSession), \
         patch("backend.agent_templates.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _seed_task(TestSession, *, dod=None, assignee="", branch="", pr_url="",
                gates_enabled=False) -> str:
    p = core_services.create_project("G", actor="system")
    if gates_enabled:
        core_services.update_project(p["id"], gates_enabled=True)
    t = core_services.create_task(
        p["id"], "T", actor="system", assignee=assignee or "",
    )
    if dod is not None or branch or pr_url:
        with TestSession() as db:
            row = db.get(Task, t["id"])
            if dod is not None:
                row.dod_items = _json.dumps(dod)
            row.branch = branch
            row.pr_url = pr_url
            db.commit()
    return t["id"]


# ── Individual gate checkers ───────────────────────────────────────────

def test_has_dod_blocks_empty_or_missing(test_db):
    t = _seed_task(test_db)
    with test_db() as db:
        row = db.get(Task, t)
        assert gates._has_dod(row).ok is False
    # Set an empty array — still fails.
    with test_db() as db:
        row = db.get(Task, t)
        row.dod_items = "[]"
        db.commit()
        assert gates._has_dod(row).ok is False


def test_has_dod_passes_with_at_least_one_item(test_db):
    t = _seed_task(test_db, dod=[{"text": "ship", "checked": False}])
    with test_db() as db:
        row = db.get(Task, t)
        assert gates._has_dod(row).ok is True


def test_has_assignee_blocks_empty(test_db):
    t = _seed_task(test_db)
    with test_db() as db:
        row = db.get(Task, t)
        assert gates._has_assignee(row).ok is False


def test_has_assignee_passes_when_set(test_db):
    t = _seed_task(test_db, assignee="Backend Implementer")
    with test_db() as db:
        row = db.get(Task, t)
        assert gates._has_assignee(row).ok is True


def test_dod_all_checked_fails_with_open_items(test_db):
    t = _seed_task(test_db, dod=[
        {"text": "tests", "checked": True},
        {"text": "docs", "checked": False},
    ])
    with test_db() as db:
        row = db.get(Task, t)
        res = gates._dod_all_checked(row)
        assert res.ok is False
        assert "docs" in res.reason


def test_dod_all_checked_passes_when_all_checked(test_db):
    t = _seed_task(test_db, dod=[
        {"text": "tests", "checked": True},
        {"text": "ship", "checked": True},
    ])
    with test_db() as db:
        row = db.get(Task, t)
        assert gates._dod_all_checked(row).ok is True


def test_has_branch_or_pr_accepts_either(test_db):
    t1 = _seed_task(test_db, branch="feat/x")
    t2 = _seed_task(test_db, pr_url="https://github.com/o/r/pull/1")
    t3 = _seed_task(test_db)
    with test_db() as db:
        assert gates._has_branch_or_pr(db.get(Task, t1)).ok is True
        assert gates._has_branch_or_pr(db.get(Task, t2)).ok is True
        assert gates._has_branch_or_pr(db.get(Task, t3)).ok is False


def test_pr_url_set_requires_pr(test_db):
    t1 = _seed_task(test_db, pr_url="https://github.com/o/r/pull/9")
    t2 = _seed_task(test_db, branch="feat/x")  # branch alone isn't enough
    with test_db() as db:
        assert gates._pr_url_set(db.get(Task, t1)).ok is True
        assert gates._pr_url_set(db.get(Task, t2)).ok is False


# ── Engine ─────────────────────────────────────────────────────────────

def test_evaluate_returns_empty_for_unknown_transition(test_db):
    t = _seed_task(test_db)
    with test_db() as db:
        row = db.get(Task, t)
        assert gates.evaluate(row, from_status="review",
                               to_status="in_progress") == []


def test_evaluate_runs_all_gates_for_backlog_todo(test_db):
    t = _seed_task(test_db)  # no DoD, no assignee
    with test_db() as db:
        row = db.get(Task, t)
        results = gates.evaluate(row, from_status="backlog", to_status="todo")
        names = {r.name for r in results}
        assert names == {"has_dod", "has_assignee"}
        # Both fail.
        assert all(r.ok is False for r in results)


def test_enforce_raises_with_structured_failure(test_db):
    t = _seed_task(test_db)
    with test_db() as db:
        row = db.get(Task, t)
        with pytest.raises(gates.GateFailure) as exc:
            gates.enforce(row, from_status="backlog", to_status="todo")
    payload = exc.value.to_dict()
    assert payload["error"] == "transition_blocked"
    assert payload["from_status"] == "backlog"
    assert payload["to_status"] == "todo"
    failed = {g["name"] for g in payload["failed_gates"]}
    assert failed == {"has_dod", "has_assignee"}


def test_enforce_passes_when_all_gates_pass(test_db):
    t = _seed_task(test_db,
                    dod=[{"text": "ship", "checked": False}],
                    assignee="Backend Implementer")
    with test_db() as db:
        row = db.get(Task, t)
        gates.enforce(row, from_status="backlog", to_status="todo")  # no raise


# ── End-to-end: move_task respects gates_enabled ──────────────────────

def test_move_task_blocked_when_gates_enabled_and_gate_fails(test_db):
    t = _seed_task(test_db, gates_enabled=True)  # no DoD, no assignee
    with pytest.raises(gates.GateFailure):
        core_services.move_task(t, "todo", actor="system")


def test_move_task_allowed_when_gates_disabled(test_db):
    """Gates are opt-in — projects without `gates_enabled` get today's
    behavior (move passes, only RBAC is checked)."""
    t = _seed_task(test_db)  # gates_enabled=False, no DoD, no assignee
    out = core_services.move_task(t, "todo", actor="system")
    assert out["status"] == "todo"


def test_move_task_allowed_when_gates_enabled_and_all_pass(test_db):
    t = _seed_task(test_db,
                    dod=[{"text": "build", "checked": False}],
                    assignee="Backend Implementer",
                    gates_enabled=True)
    out = core_services.move_task(t, "todo", actor="system")
    assert out["status"] == "todo"


def test_move_to_done_requires_pr_and_all_dod_checked(test_db):
    t = _seed_task(test_db,
                    dod=[{"text": "ship", "checked": True}],
                    assignee="A", branch="feat/x", pr_url="",
                    gates_enabled=True)
    # First move it through to review.
    core_services.move_task(t, "todo", actor="system")
    core_services.move_task(t, "in_progress", actor="system")
    core_services.move_task(t, "review", actor="system")
    # Now blocked at review→done because no PR URL.
    with pytest.raises(gates.GateFailure) as exc:
        core_services.move_task(t, "done", actor="system")
    names = {g.name for g in exc.value.failed_gates}
    assert "pr_url_set" in names


# ── Project Settings round-trip ───────────────────────────────────────

def test_project_gates_enabled_persists_via_update_project(test_db):
    p = core_services.create_project("PG", actor="system")
    out = core_services.update_project(p["id"], gates_enabled=True)
    assert out["gates_enabled"] is True
    again = core_services.get_project(p["id"])
    assert again["gates_enabled"] is True
    cleared = core_services.update_project(p["id"], gates_enabled=False)
    assert cleared["gates_enabled"] is False
