"""AP-129: assigning an agent to a task creates a READY run.

Before: the assignment trigger fired schedule_task_run, which dispatched
the run immediately — the user had no chance to review the prepared
prompt before tokens were spent. After: the trigger fires
prepare_task_run, which lands in READY waiting on an explicit Start.
"""

from __future__ import annotations

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge import triggers as forge_triggers
from backend.forge.models import (
    ForgeRuntime, Run, RunStatus, RuntimeStatus,
)


@pytest.fixture(autouse=True)
def test_db(pg):
    yield bdb.SessionLocal


def _setup(TestSession):
    db = TestSession()
    rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                      status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "Build the thing",
                                     actor="system")
    agent = forge_services.create_agent(name="bot1", executor_type="cli",
                                        runtime_id=rt_id)
    return {"task_id": task["id"], "agent_id": agent["id"]}


def _runs_for_task(TestSession, task_id: str) -> list[Run]:
    db = TestSession()
    try:
        return (db.query(Run)
                  .filter(Run.task_id == task_id)
                  .order_by(Run.created_at.asc())
                  .all())
    finally:
        db.close()


# ── READY, not RUNNING ───────────────────────────────────────────────

def test_assignment_creates_ready_run(test_db):
    """The whole point of AP-129: assigning lands a READY row, not a
    RUNNING one. No tokens spent until the user clicks Start."""
    s = _setup(test_db)
    forge_triggers.fire_task_assigned(s["task_id"], "bot1")
    runs = _runs_for_task(test_db, s["task_id"])
    assert len(runs) == 1, "should create exactly one run"
    assert runs[0].status == RunStatus.READY, runs[0].status.value


def test_assignment_persists_initial_prompt(test_db):
    """READY rows carry the prepared prompt so the user can edit it
    before pressing Start. Confirm prepare_task_run's work landed."""
    s = _setup(test_db)
    forge_triggers.fire_task_assigned(s["task_id"], "bot1")
    runs = _runs_for_task(test_db, s["task_id"])
    assert runs[0].initial_prompt
    assert "Build the thing" in runs[0].initial_prompt


def test_assignment_to_unknown_agent_is_a_noop(test_db):
    """Assigning to a human (or any name with no matching forge agent)
    creates nothing — same as before AP-129."""
    s = _setup(test_db)
    forge_triggers.fire_task_assigned(s["task_id"], "alice-human")
    assert _runs_for_task(test_db, s["task_id"]) == []


def test_assignment_to_runtime_less_agent_is_a_noop(test_db):
    """An agent with no runtime bound can't be dispatched. The trigger
    silently skips (logged) rather than creating an orphaned run."""
    db = test_db()
    bot = core_services.create_service_account("orphaned-bot")
    db.close()
    forge_services.create_agent(name="orphaned-bot", executor_type="cli",
                                runtime_id=None)
    s = _setup(test_db)
    forge_triggers.fire_task_assigned(s["task_id"], "orphaned-bot")
    assert _runs_for_task(test_db, s["task_id"]) == []


# ── conductor path unaffected ────────────────────────────────────────

def test_conductor_path_still_auto_dispatches(test_db, monkeypatch):
    """The Conductor's autopilot tick goes through schedule_task_run
    DIRECTLY (not through fire_task_assigned). AP-129 must not break
    that — assigning a Conductor-managed task to an idle conductor-
    enabled agent should still result in a dispatched run."""
    s = _setup(test_db)
    calls = []

    def fake_schedule(*args, **kwargs):
        calls.append(kwargs)
        return {"run_id": "fake", "ok": True}

    monkeypatch.setattr(forge_services, "schedule_task_run", fake_schedule)
    forge_services.schedule_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    assert len(calls) == 1
    assert calls[0]["task_id"] == s["task_id"]
