"""Conductor progress watchdog (AP-232).

Code+LLM split, same shape as the planning turn:
- gather_progress_facts (token-free) detects stalled tasks in projects
  the Conductor manages — latest run failed terminally OR went quiet
  beyond the threshold.
- run_progress_check_turn skips when nothing stalled, otherwise dispatches
  one judgment turn whose prompt comes from
  templates/conductor/progress_check.md (prompts-are-config).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge import conductor
from backend.forge.models import (Agent, ForgeRuntime, Run, RunOutcome,
                                  RunStatus)


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg


def _mk_runtime(db) -> str:
    rt = ForgeRuntime(id=uuid.uuid4().hex[:12], daemon_id="d1",
                      provider="claude", binary_path="/bin/claude",
                      status="online")
    db.add(rt)
    db.commit()
    return rt.id


def _mk_conductor_agent(*, name="impl"):
    """Create one conductor-enabled agent bound to a fresh project, and
    return (agent_id, project_id)."""
    bot = core_services.create_service_account(name)
    proj = core_services.create_project(f"P_{name}")
    from backend.models import Profile
    with forge_services._session() as db:
        rt_id = _mk_runtime(db)
        prof = db.get(Profile, bot["id"])
        prof.default_project_id = proj["id"]
        prof.conductor_enabled = True
        prof.runtime_id = rt_id
        db.add(Agent(id=bot["id"], profile_id=bot["id"], name=name,
                     executor_type="http", model="", runtime_id=rt_id))
        db.commit()
    return bot["id"], proj["id"]


def _mk_task(*, project_id: str, status_name: str, assignee: str = ""):
    from backend.models import Status, Task
    with forge_services._session() as db:
        st = db.query(Status).filter(Status.name == status_name).first()
        t = Task(project_id=project_id,
                 key=f"T-{uuid.uuid4().hex[:4]}",
                 title=f"Task in {status_name}", description="",
                 status_id=st.id, assignee=assignee)
        db.add(t)
        db.commit()
        return t.id


def _mk_run(*, agent_id: str, task_id: str, project_id: str,
            status: RunStatus, outcome: RunOutcome | None = None,
            error: str = "", minutes_ago: int = 0):
    """Attach a run to the task with a controlled last-activity timestamp."""
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    with forge_services._session() as db:
        r = Run(agent_id=agent_id, task_id=task_id, project_id=project_id,
                status=status, outcome=outcome, error=error,
                last_heartbeat_at=ts, created_at=ts)
        db.add(r)
        db.commit()
        return r.id


# ── gather_progress_facts ────────────────────────────────────────────────


def test_no_managed_projects_returns_empty(test_db):
    """Without a conductor-enabled agent anywhere, the watchdog has nothing
    to scope to and quietly returns no stalled work."""
    facts = conductor.gather_progress_facts()
    assert facts == {"stalled_tasks": [], "threshold_minutes":
                     conductor.STALLED_NO_ACTIVITY_MINUTES}


def test_task_without_a_run_is_not_stalled(test_db):
    """A task in_progress with no run yet is the planning turn's concern,
    not the watchdog's — never flag it."""
    agent_id, pid = _mk_conductor_agent()
    _mk_task(project_id=pid, status_name="in_progress")
    assert conductor.gather_progress_facts()["stalled_tasks"] == []


def test_failed_run_surfaces_as_stalled(test_db):
    agent_id, pid = _mk_conductor_agent()
    tid = _mk_task(project_id=pid, status_name="in_progress",
                   assignee="impl")
    _mk_run(agent_id=agent_id, task_id=tid, project_id=pid,
            status=RunStatus.FAILED, outcome=RunOutcome.FAILED,
            error="boom", minutes_ago=2)
    facts = conductor.gather_progress_facts()
    stalled = facts["stalled_tasks"]
    assert len(stalled) == 1
    s = stalled[0]
    assert s["task_id"] == tid
    assert s["stalled_reason"] in ("last_run_failed", "last_run_failed_and_idle")
    assert s["assignee"] == "impl"
    assert s["last_run"]["error"] == "boom"


def test_quiet_run_beyond_threshold_is_stalled(test_db):
    """A non-terminal run whose heartbeat is old → stalled by no_activity."""
    agent_id, pid = _mk_conductor_agent()
    tid = _mk_task(project_id=pid, status_name="in_progress")
    _mk_run(agent_id=agent_id, task_id=tid, project_id=pid,
            status=RunStatus.RUNNING, outcome=None,
            minutes_ago=conductor.STALLED_NO_ACTIVITY_MINUTES + 5)
    facts = conductor.gather_progress_facts()
    assert len(facts["stalled_tasks"]) == 1
    assert facts["stalled_tasks"][0]["stalled_reason"] == "no_activity"
    assert facts["stalled_tasks"][0]["minutes_idle"] >= \
        conductor.STALLED_NO_ACTIVITY_MINUTES


def test_recent_healthy_run_is_not_stalled(test_db):
    agent_id, pid = _mk_conductor_agent()
    tid = _mk_task(project_id=pid, status_name="in_progress")
    _mk_run(agent_id=agent_id, task_id=tid, project_id=pid,
            status=RunStatus.RUNNING, outcome=None, minutes_ago=2)
    assert conductor.gather_progress_facts()["stalled_tasks"] == []


def test_review_tasks_are_scanned_too(test_db):
    """A succeeded run that didn't advance the task off `review` is the
    canonical workflow-gap case — must show up in the watchdog."""
    agent_id, pid = _mk_conductor_agent()
    tid = _mk_task(project_id=pid, status_name="review", assignee="impl")
    _mk_run(agent_id=agent_id, task_id=tid, project_id=pid,
            status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
            minutes_ago=conductor.STALLED_NO_ACTIVITY_MINUTES + 10)
    facts = conductor.gather_progress_facts()
    assert len(facts["stalled_tasks"]) == 1
    s = facts["stalled_tasks"][0]
    assert s["status"] == "review"
    assert s["stalled_reason"] == "no_activity"


def test_threshold_is_overrideable(test_db):
    """The cadence is config — callers can pass a tighter window."""
    agent_id, pid = _mk_conductor_agent()
    tid = _mk_task(project_id=pid, status_name="in_progress")
    _mk_run(agent_id=agent_id, task_id=tid, project_id=pid,
            status=RunStatus.RUNNING, outcome=None, minutes_ago=10)
    assert conductor.gather_progress_facts(stale_minutes=5)["stalled_tasks"]
    assert not conductor.gather_progress_facts(stale_minutes=30)["stalled_tasks"]


# ── run_progress_check_turn ──────────────────────────────────────────────


def test_progress_turn_skips_when_nothing_stalled(test_db):
    _, pid = _mk_conductor_agent()
    conductor.get_or_create_conductor()
    calls = []
    with patch.object(forge_services, "send_runtime_message",
                      lambda *a, **k: calls.append(k)):
        result = conductor.run_progress_check_turn()
    assert result["projects"] == [{"project_id": pid, "skipped": "nothing_stalled"}]
    assert calls == []


def test_progress_turn_dispatches_llm_turn_when_stalled(test_db):
    agent_id, pid = _mk_conductor_agent()
    tid = _mk_task(project_id=pid, status_name="in_progress",
                   assignee="impl")
    _mk_run(agent_id=agent_id, task_id=tid, project_id=pid,
            status=RunStatus.FAILED, outcome=RunOutcome.FAILED,
            error="explode", minutes_ago=2)
    conductor.get_or_create_conductor()
    calls: list[dict] = []
    with patch.object(forge_services, "send_runtime_message",
                      lambda *a, **k: calls.append(k)):
        result = conductor.run_progress_check_turn()
    proj_result = result["projects"][0]
    assert proj_result["ok"] is True
    assert proj_result["project_id"] == pid
    assert proj_result["stalled"] == 1
    assert proj_result["threshold_minutes"] == conductor.STALLED_NO_ACTIVITY_MINUTES
    assert proj_result["scope_key"] == f"turn:{proj_result['turn_id']}"
    assert len(calls) == 1
    sent = calls[0]
    content = sent["content"]
    assert sent["scope_key"] == proj_result["scope_key"]
    assert "PROGRESS CHECK" in content                           # template loaded
    assert str(tid) in content                                   # facts injected
    assert "explode" in content                                  # error surfaced
    assert "stalled_reason=" in content                          # row format

    turns = conductor.get_recent_planning_turns()
    turn = next(t for t in turns if t["trigger"] == "progress_check")
    assert turn["conversation_scope_key"] == proj_result["scope_key"]


def test_progress_turn_off_when_conductor_disabled(test_db):
    """Master switch: no facts gathered, no LLM call."""
    cond = conductor.get_or_create_conductor()
    forge_services.update_agent(cond["id"], conductor_active=False)
    calls = []
    with patch.object(forge_services, "send_runtime_message",
                      lambda *a, **k: calls.append(k)):
        result = conductor.run_progress_check_turn()
    assert result == {"skipped": "conductor_disabled"}
    assert calls == []
