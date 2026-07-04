"""Regression test for the 2026-07-04 incident sweep: gather_planning_facts
and gather_progress_facts scanned tasks with no LIMIT — same unbounded-scan
shape as the /api/notifications OOM (#161), but on jobs that fire every
plan_interval_minutes (planning) / 10 minutes (progress). Also covers the
N+1 fix in gather_progress_facts: one Run query per task was replaced with
a single batched query — this must still pick each task's LATEST run.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge import conductor
from backend.forge.models import Agent, Run, RunStatus, ForgeRuntime
from backend.models import Task, Status, Profile


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg


def _mk_conductor_agent() -> tuple[str, str]:
    """One conductor-enabled agent bound to a fresh project."""
    bot = core_services.create_service_account("bot1")
    proj = core_services.create_project("P1")
    with forge_services._session() as db:
        rt = ForgeRuntime(id=uuid.uuid4().hex[:12], daemon_id="d1",
                          provider="claude", binary_path="/bin/claude",
                          status="online")
        db.add(rt)
        db.commit()
        prof = db.get(Profile, bot["id"])
        prof.default_project_id = proj["id"]
        prof.conductor_enabled = True
        prof.runtime_id = rt.id
        a = Agent(id=bot["id"], profile_id=bot["id"], name="bot1",
                  executor_type="http", model="", runtime_id=rt.id)
        db.add(a)
        db.commit()
        agent_id = a.id
    return agent_id, proj["id"]


def test_gather_planning_facts_bounds_unassigned_scan():
    """Seeding more unassigned todo tasks than FACTS_SCAN_LIMIT must not
    return them all — the scan needs a SQL-level LIMIT."""
    _, project_id = _mk_conductor_agent()
    n = conductor.FACTS_SCAN_LIMIT + 10
    with forge_services._session() as db:
        todo = db.query(Status).filter(Status.name == "todo").first()
        for i in range(n):
            db.add(Task(project_id=project_id, key=f"P1-{i}", title=f"t{i}",
                       description="", status_id=todo.id, assignee=""))
        db.commit()
    facts = conductor.gather_planning_facts()
    assert len(facts["unassigned_tasks"]) == conductor.FACTS_SCAN_LIMIT


def test_gather_progress_facts_bounds_stalled_scan():
    """Seeding more stalled in_progress tasks than FACTS_SCAN_LIMIT must not
    return them all — the scan needs a SQL-level LIMIT."""
    agent_id, project_id = _mk_conductor_agent()
    n = conductor.FACTS_SCAN_LIMIT + 10
    stale_ts = datetime.now(timezone.utc) - timedelta(minutes=60)
    with forge_services._session() as db:
        ip = db.query(Status).filter(Status.name == "in_progress").first()
        for i in range(n):
            t = Task(project_id=project_id, key=f"P2-{i}", title=f"t{i}",
                     description="", status_id=ip.id, assignee=agent_id)
            db.add(t)
            db.flush()
            db.add(Run(agent_id=agent_id, task_id=t.id,
                       status=RunStatus.RUNNING, started_at=stale_ts,
                       created_at=stale_ts))
        db.commit()
    facts = conductor.gather_progress_facts()
    assert len(facts["stalled_tasks"]) == conductor.FACTS_SCAN_LIMIT


def test_gather_progress_facts_picks_latest_run_per_task():
    """N+1 fix regression: the batched query must still pick each task's
    LATEST run, not an older one, when a task has more than one run."""
    agent_id, project_id = _mk_conductor_agent()
    now = datetime.now(timezone.utc)
    older = now - timedelta(minutes=60)
    newer = now - timedelta(minutes=1)
    with forge_services._session() as db:
        ip = db.query(Status).filter(Status.name == "in_progress").first()
        t = Task(project_id=project_id, key="P3-1", title="t",
                 description="", status_id=ip.id, assignee=agent_id)
        db.add(t)
        db.flush()
        task_id = t.id
        # Older run failed (would flag the task as stalled if picked)...
        db.add(Run(agent_id=agent_id, task_id=task_id,
                   status=RunStatus.FAILED, started_at=older, created_at=older))
        # ...but the newer run is healthy and fresh (1 min old).
        db.add(Run(agent_id=agent_id, task_id=task_id,
                   status=RunStatus.RUNNING, started_at=newer, created_at=newer))
        db.commit()

    facts = conductor.gather_progress_facts()
    matches = [s for s in facts["stalled_tasks"] if s["task_id"] == task_id]
    assert matches == [], (
        "picked the older FAILED run instead of the latest RUNNING one")
