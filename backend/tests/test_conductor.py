"""AP-80 Conductor — pick_next_unblocked + run_tick.

Verifies:
  - pick_next_unblocked respects todo status + project + assignee match
  - run_tick skips agents with no conductor flag, no runtime, no eligible task
  - run_tick dispatches via schedule_task_run for idle eligible agents
  - max_concurrent_runs cap is honored
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge import conductor
from backend.forge.models import (
    Agent, Run, RunStatus, ForgeRuntime, AgentMessage, MessageRole,
)


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.runs.SessionLocal", TestSession), \
         patch("backend.forge.conductor.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _mk_runtime(db) -> str:
    rt = ForgeRuntime(id=uuid.uuid4().hex[:12], daemon_id="d1",
                      provider="claude", binary_path="/bin/claude",
                      status="online")
    db.add(rt)
    db.commit()
    return rt.id


def _mk_setup(*, conductor_enabled: bool = True,
              max_concurrent: int = 1,
              assignee: str = "bot1") -> tuple[str, str, str]:
    """Bootstrap one agent + project + todo task. Returns (agent_id, project_id, task_id).

    The task defaults to ASSIGNED to the agent — AP-203 made the tick
    assigned-only (the LLM planner owns who gets what; the deterministic tick
    only dispatches what was assigned). Pass assignee="" to model the
    pre-planning state."""
    bot = core_services.create_service_account("bot1")
    proj = core_services.create_project("P1")
    from backend.models import Task, Status, Profile

    with forge_services._session() as db:
        rt_id = _mk_runtime(db)
        prof = db.get(Profile, bot["id"])
        prof.default_project_id = proj["id"]
        prof.conductor_enabled = conductor_enabled
        prof.max_concurrent_runs = max_concurrent
        prof.runtime_id = rt_id
        a = Agent(id=bot["id"], profile_id=bot["id"], name="bot1",
                  executor_type="http", model="", runtime_id=rt_id)
        db.add(a)
        todo_status = db.query(Status).filter(Status.name == "todo").first()
        t = Task(id=uuid.uuid4().hex, project_id=proj["id"],
                 key="P1-1", title="Task 1", description="",
                 status_id=todo_status.id, assignee=assignee)
        db.add(t)
        db.commit()
        return a.id, proj["id"], t.id


def test_pick_next_returns_assigned_todo():
    agent_id, project_id, task_id = _mk_setup()
    chosen = conductor.pick_next_unblocked(
        project_id=project_id, agent_id=agent_id,
    )
    assert chosen is not None
    assert chosen.id == task_id


def test_pick_next_ignores_unassigned_todo():
    """AP-203: the tick no longer FIFO-grabs unassigned tasks — they wait for
    the LLM planning turn to assign an owner."""
    agent_id, project_id, _ = _mk_setup(assignee="")
    chosen = conductor.pick_next_unblocked(
        project_id=project_id, agent_id=agent_id,
    )
    assert chosen is None


def test_pick_next_returns_none_when_no_todo_exists():
    agent_id, project_id, _ = _mk_setup()
    # Move the task out of todo.
    from backend.models import Task, Status
    with forge_services._session() as db:
        review_status = db.query(Status).filter(Status.name == "review").first()
        db.query(Task).update({"status_id": review_status.id})
        db.commit()
    chosen = conductor.pick_next_unblocked(
        project_id=project_id, agent_id=agent_id,
    )
    assert chosen is None


def test_pick_next_skips_task_assigned_to_other_agent():
    agent_id, project_id, _ = _mk_setup()
    from backend.models import Task
    with forge_services._session() as db:
        db.query(Task).update({"assignee": "other-agent"})
        db.commit()
    chosen = conductor.pick_next_unblocked(
        project_id=project_id, agent_id=agent_id,
    )
    assert chosen is None


def test_run_tick_dispatches_eligible_agent():
    agent_id, _, task_id = _mk_setup()
    calls = []
    def fake_schedule(*, task_id, agent_id):
        calls.append((task_id, agent_id))
        return {"run_id": "fake-run-id"}
    with patch.object(forge_services, "schedule_task_run", fake_schedule):
        result = conductor.run_tick()
    assert len(calls) == 1
    assert calls[0] == (task_id, agent_id)
    assert len(result["dispatched"]) == 1
    assert result["dispatched"][0]["task"] == task_id


def test_run_tick_skips_conductor_disabled_agent():
    _mk_setup(conductor_enabled=False)
    calls = []
    with patch.object(forge_services, "schedule_task_run",
                      lambda **kw: (calls.append(kw), {"run_id": "x"})[1]):
        result = conductor.run_tick()
    assert calls == []
    # No profiles match the filter, so dispatched + skipped are both empty.
    assert result["dispatched"] == []


def test_run_tick_respects_max_concurrent_runs():
    agent_id, _, task_id = _mk_setup(max_concurrent=1)
    # Pre-seed a running run so the agent is at capacity.
    with forge_services._session() as db:
        db.add(Run(id=uuid.uuid4().hex[:12], agent_id=agent_id,
                   status=RunStatus.RUNNING))
        db.commit()
    calls = []
    with patch.object(forge_services, "schedule_task_run",
                      lambda **kw: (calls.append(kw), {"run_id": "x"})[1]):
        result = conductor.run_tick()
    assert calls == []
    assert any(s.get("reason") == "at_capacity" for s in result["skipped"])


# ── Runaway-guard tests (the "schedules indefinitely" fix) ───────────────

def test_pick_next_excludes_task_that_already_has_a_run():
    """Core runaway guard: a todo task that already has a Run is never
    auto-picked again — even if it's still in todo (e.g. its run failed
    and nothing moved it). Without this the Conductor re-dispatches the
    same task every tick forever."""
    agent_id, project_id, task_id = _mk_setup()
    with forge_services._session() as db:
        db.add(Run(id=uuid.uuid4().hex[:12], agent_id=agent_id,
                   task_id=task_id, status=RunStatus.FAILED))
        db.commit()
    chosen = conductor.pick_next_unblocked(
        project_id=project_id, agent_id=agent_id,
    )
    assert chosen is None, "task with an existing run must not be re-picked"


def test_run_tick_moves_dispatched_task_to_in_progress():
    """On dispatch the task is claimed — moved todo -> in_progress — so it
    leaves the auto-pick pool immediately."""
    agent_id, _, task_id = _mk_setup()
    with patch.object(forge_services, "schedule_task_run",
                      lambda **kw: {"run_id": "r1"}):
        conductor.run_tick()
    from backend.models import Task, Status
    with forge_services._session() as db:
        t = db.get(Task, task_id)
        ip = db.query(Status).filter(Status.name == "in_progress").first()
        assert t.status_id == ip.id, "dispatched task must move to in_progress"


def test_conductor_does_not_redispatch_across_two_ticks():
    """End-to-end runaway check: two ticks in a row dispatch the task at
    most once. Tick 1 dispatches + claims it; tick 2 finds nothing."""
    agent_id, _, task_id = _mk_setup()
    calls = []

    def fake_schedule(*, task_id, agent_id):
        calls.append(task_id)
        # Mimic schedule_task_run creating the Run row.
        with forge_services._session() as db:
            db.add(Run(id=uuid.uuid4().hex[:12], agent_id=agent_id,
                       task_id=task_id, status=RunStatus.RUNNING))
            db.commit()
        return {"run_id": "r-" + task_id}

    with patch.object(forge_services, "schedule_task_run", fake_schedule):
        conductor.run_tick()
        conductor.run_tick()
    assert len(calls) == 1, f"task dispatched {len(calls)}x — runaway not fixed"


def test_get_or_create_conductor_is_idempotent():
    a = conductor.get_or_create_conductor()
    b = conductor.get_or_create_conductor()
    assert a.get("id") and a["id"] == b["id"]
    assert a["name"] == conductor.CONDUCTOR_NAME


def test_survey_workspace_reports_next_task():
    agent_id, _, task_id = _mk_setup()
    snap = conductor.survey_workspace()
    mine = [a for a in snap["agents"] if a["agent"] == agent_id]
    assert len(mine) == 1
    assert mine[0]["next_task"]["id"] == task_id


# ── AP-119: stale-run reconciler ─────────────────────────────────────────

def _mk_run(agent_id, *, status, age_minutes, task_id=None):
    from datetime import datetime, timedelta, timezone
    ts = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    rid = uuid.uuid4().hex[:12]
    with forge_services._session() as db:
        db.add(Run(id=rid, agent_id=agent_id, task_id=task_id,
                   status=status, started_at=ts, created_at=ts))
        db.commit()
    return rid


def test_reconcile_fails_zombie_running_run():
    """A RUNNING run silent past the threshold is marked FAILED."""
    agent_id, _, _ = _mk_setup()
    rid = _mk_run(agent_id, status=RunStatus.RUNNING, age_minutes=45)
    out = conductor.reconcile_stale_runs()
    assert any(r["run"] == rid for r in out)
    with forge_services._session() as db:
        assert db.get(Run, rid).status == RunStatus.FAILED


def test_reconcile_leaves_fresh_running_run_alone():
    agent_id, _, _ = _mk_setup()
    rid = _mk_run(agent_id, status=RunStatus.RUNNING, age_minutes=2)
    conductor.reconcile_stale_runs()
    with forge_services._session() as db:
        assert db.get(Run, rid).status == RunStatus.RUNNING


def test_reconcile_uses_recent_message_as_activity():
    """A run is NOT stale if it has a recent message, even if old."""
    agent_id, _, _ = _mk_setup()
    rid = _mk_run(agent_id, status=RunStatus.RUNNING, age_minutes=90)
    with forge_services._session() as db:
        db.add(AgentMessage(agent_id=agent_id, run_id=rid,
                            role=MessageRole.ASSISTANT, content="still working"))
        db.commit()
    conductor.reconcile_stale_runs()
    with forge_services._session() as db:
        assert db.get(Run, rid).status == RunStatus.RUNNING


def test_run_tick_reports_reconciled():
    agent_id, _, _ = _mk_setup()
    _mk_run(agent_id, status=RunStatus.RUNNING, age_minutes=45)
    with patch.object(forge_services, "schedule_task_run",
                      lambda **kw: {"run_id": "x"}):
        result = conductor.run_tick()
    assert "reconciled" in result
    assert len(result["reconciled"]) == 1


# ── tick_agent: event-driven "agent freed" scheduling ────────────────────

def test_tick_agent_dispatches_next_assigned_task():
    agent_id, project_id, task_id = _mk_setup()
    calls = []
    def fake_schedule(*, task_id, agent_id):
        calls.append((task_id, agent_id))
        return {"run_id": "r1"}
    with patch.object(forge_services, "schedule_task_run", fake_schedule):
        out = conductor.tick_agent(agent_id)
    assert out["dispatched"] is True
    assert calls == [(task_id, agent_id)]
    # claimed: task moved to in_progress
    from backend.models import Task, Status
    with forge_services._session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "in_progress"


def test_tick_agent_respects_capacity():
    """The per-agent counting semaphore: at cap -> no dispatch."""
    agent_id, project_id, task_id = _mk_setup(max_concurrent=1)
    from backend.forge.models import Run, RunStatus
    with forge_services._session() as db:
        db.add(Run(agent_id=agent_id, project_id=project_id,
                   status=RunStatus.RUNNING))
        db.commit()
    out = conductor.tick_agent(agent_id)
    assert out == {"dispatched": False, "reason": "at_capacity"}


def test_tick_agent_noop_when_nothing_assigned():
    agent_id, project_id, _ = _mk_setup(assignee="")
    out = conductor.tick_agent(agent_id)
    assert out == {"dispatched": False, "reason": "no_eligible_task"}


def test_tick_agent_respects_master_switch():
    agent_id, *_ = _mk_setup()
    from backend.models import Profile
    with forge_services._session() as db:
        # The Conductor profile's conductor_active is the master switch.
        prof = db.query(Profile).filter(Profile.name == "Conductor").first()
        if prof is None:
            conductor.get_or_create_conductor()
            prof = db.query(Profile).filter(Profile.name == "Conductor").first()
        prof.conductor_active = False
        db.commit()
    out = conductor.tick_agent(agent_id)
    assert out == {"dispatched": False, "reason": "conductor_disabled"}
