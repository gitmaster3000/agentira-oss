"""Conductor planning turn — the LLM assigns the unassigned todo backlog.

The deterministic queue tick DISPATCHES; the planning turn is the LLM
deciding WHO gets WHAT. Facts are gathered token-free, PER PROJECT (AP-4xx
turn-scopes rework — a turn never mixes more than one project's tasks); the
LLM only decides; it assigns by calling update_task (assignee). Runs only
when there is unassigned work or promotable backlog for that project.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge import conductor
from backend.forge.models import Agent, ForgeRuntime


@pytest.fixture(autouse=True)
def _conductor_runtime_live(monkeypatch):
    """These tests cover turn content, not delivery: treat the Conductor's
    (unconnected) test runtime as live. Liveness: test_conductor_liveness.py."""
    from backend.forge import conductor as _c
    monkeypatch.setattr(_c, "_runtime_live", lambda runtime_id: True)



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


def _mk_setup(*, conductor_enabled=True):
    """One conductor-enabled agent + project + an unassigned todo task."""
    bot = core_services.create_service_account("bot1")
    proj = core_services.create_project("P1")
    from backend.models import Task, Status, Profile
    with forge_services._session() as db:
        rt_id = _mk_runtime(db)
        prof = db.get(Profile, bot["id"])
        prof.default_project_id = proj["id"]
        prof.conductor_enabled = conductor_enabled
        prof.runtime_id = rt_id
        a = Agent(id=bot["id"], profile_id=bot["id"], name="bot1",
                  executor_type="http", model="", runtime_id=rt_id)
        db.add(a)
        todo = db.query(Status).filter(Status.name == "todo").first()
        t = Task(project_id=proj["id"], key="P1-1",
                 title="Build the parser", description="", status_id=todo.id,
                 assignee="")
        db.add(t)
        db.commit()
        return a.id, proj["id"], t.id


# ── config ─────────────────────────────────────────────────────────────

def test_config_includes_plan_interval(test_db):
    conductor.get_or_create_conductor()
    cfg = conductor.get_conductor_config()
    assert cfg["plan_interval_minutes"] == 10


def test_plan_interval_is_configurable_and_floored(test_db):
    cond = conductor.get_or_create_conductor()
    forge_services.update_agent(cond["id"], conductor_plan_interval_minutes=20)
    assert conductor.get_conductor_config()["plan_interval_minutes"] == 20
    # A nonsensical value is floored to a 1-minute minimum.
    forge_services.update_agent(cond["id"], conductor_plan_interval_minutes=-3)
    assert conductor.get_conductor_config()["plan_interval_minutes"] == 1


# ── fact gathering (per project) ─────────────────────────────────────────

def test_gather_planning_facts_lists_unassigned_todo(test_db):
    agent_id, project_id, task_id = _mk_setup()
    facts = conductor.gather_planning_facts(project_id)
    assert facts["project_id"] == project_id
    assert facts["project_name"] == "P1"
    assert any(a["name"] == "bot1" for a in facts["agents"])
    assert any(t["id"] == task_id for t in facts["unassigned_tasks"])


def test_gather_planning_facts_excludes_assigned_tasks(test_db):
    agent_id, project_id, task_id = _mk_setup()
    from backend.models import Task
    with forge_services._session() as db:
        db.query(Task).filter(Task.id == task_id).update({"assignee": "bot1"})
        db.commit()
    facts = conductor.gather_planning_facts(project_id)
    assert task_id not in [t["id"] for t in facts["unassigned_tasks"]]


def test_gather_planning_facts_excludes_task_with_active_run(test_db):
    agent_id, project_id, task_id = _mk_setup()
    from backend.forge.models import Run, RunStatus
    with forge_services._session() as db:
        db.add(Run(id=uuid.uuid4().hex[:12], agent_id=agent_id,
                   task_id=task_id, status=RunStatus.RUNNING))
        db.commit()
    facts = conductor.gather_planning_facts(project_id)
    assert task_id not in [t["id"] for t in facts["unassigned_tasks"]]


def test_gather_planning_facts_excludes_task_with_completed_run(test_db):
    agent_id, project_id, task_id = _mk_setup()
    from datetime import datetime, timedelta, timezone
    from backend.forge.models import Run, RunStatus
    with forge_services._session() as db:
        db.add(Run(id=uuid.uuid4().hex[:12], agent_id=agent_id,
                   task_id=task_id, status=RunStatus.COMPLETED,
                   finished_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        db.commit()
    facts = conductor.gather_planning_facts(project_id)
    assert task_id not in [t["id"] for t in facts["unassigned_tasks"]]


def test_gather_planning_facts_recovers_failed_task_after_cooldown(test_db):
    """A recovered (unassigned) task also becomes visible to the planner
    again — so it can be re-assigned, not just re-dispatched as-is."""
    agent_id, project_id, task_id = _mk_setup()
    from datetime import datetime, timedelta, timezone
    from backend.forge.models import Run, RunStatus
    with forge_services._session() as db:
        db.add(Run(id=uuid.uuid4().hex[:12], agent_id=agent_id,
                   task_id=task_id, status=RunStatus.FAILED,
                   finished_at=datetime.now(timezone.utc) - timedelta(minutes=31)))
        db.commit()
    facts = conductor.gather_planning_facts(project_id)
    assert task_id in [t["id"] for t in facts["unassigned_tasks"]]


def test_gather_planning_facts_includes_backlog_and_capacity(test_db):
    agent_id, project_id, task_id = _mk_setup()
    from backend.models import Task, Status
    with forge_services._session() as db:
        backlog = db.query(Status).filter(Status.name == "backlog").first()
        t = Task(project_id=project_id, key="P1-2", title="Backlog item",
                 description="x" * 500, status_id=backlog.id, assignee="")
        db.add(t)
        db.commit()
        backlog_task_id = t.id
    facts = conductor.gather_planning_facts(project_id)
    assert any(t["id"] == backlog_task_id for t in facts["backlog"])
    backlog_fact = next(t for t in facts["backlog"] if t["id"] == backlog_task_id)
    assert len(backlog_fact["description"]) <= 300
    assert facts["capacity"] >= 1  # bot1 has 1 free slot, 0 in-flight


# ── run_planning_turn ──────────────────────────────────────────────────

def test_planning_skips_when_nothing_unassigned(test_db):
    # conductor-enabled agent, but no todo/backlog tasks created.
    bot = core_services.create_service_account("bot1")
    proj = core_services.create_project("P1")
    from backend.models import Profile
    with forge_services._session() as db:
        rt_id = _mk_runtime(db)
        prof = db.get(Profile, bot["id"])
        prof.default_project_id = proj["id"]
        prof.conductor_enabled = True
        prof.runtime_id = rt_id
        db.add(Agent(id=bot["id"], profile_id=bot["id"], name="bot1",
                     executor_type="http", model="", runtime_id=rt_id))
        db.commit()
    conductor.get_or_create_conductor()  # binds the claude runtime
    calls = []
    with patch.object(forge_services, "send_runtime_message",
                      lambda *a, **k: calls.append(k)):
        result = conductor.run_planning_turn()
    assert result["projects"] == [{"project_id": proj["id"],
                                   "skipped": "nothing to plan"}]
    assert calls == []


def test_planning_dispatches_llm_turn_when_work_exists(test_db):
    _, project_id, task_id = _mk_setup()
    conductor.get_or_create_conductor()  # binds the claude runtime
    calls = []

    def fake_send(agent_id, *, content, scope_key=None, **kw):
        calls.append({"agent_id": agent_id, "content": content, "scope_key": scope_key})
        return {"ok": True}

    with patch.object(forge_services, "send_runtime_message", fake_send):
        result = conductor.run_planning_turn()

    assert len(result["projects"]) == 1
    proj_result = result["projects"][0]
    assert proj_result["ok"] is True
    assert proj_result["project_id"] == project_id
    assert len(calls) == 1
    assert "QUEUE PLANNING" in calls[0]["content"]
    assert "Build the parser" in calls[0]["content"]
    assert "update_task" in calls[0]["content"]
    assert calls[0]["scope_key"] == f"turn:{proj_result['turn_id']}"
    assert conductor.get_last_plan()["projects"][0]["ok"] is True


# ── master on/off ──────────────────────────────────────────────────────

def test_disabled_conductor_skips_planning(test_db):
    _mk_setup()
    cond = conductor.get_or_create_conductor()
    forge_services.update_agent(cond["id"], conductor_active=False)
    calls = []
    with patch.object(forge_services, "send_runtime_message",
                      lambda *a, **k: calls.append(k)):
        result = conductor.run_planning_turn()
    assert result.get("skipped") == "conductor_disabled"
    assert calls == []


def test_disabled_conductor_skips_tick(test_db):
    agent_id, _, task_id = _mk_setup()
    cond = conductor.get_or_create_conductor()
    forge_services.update_agent(cond["id"], conductor_active=False)
    calls = []
    with patch.object(forge_services, "schedule_task_run",
                      lambda **kw: (calls.append(kw), {"run_id": "x"})[1]):
        result = conductor.run_tick()
    assert result.get("disabled") is True
    assert result.get("skipped") == []
    assert calls == []


def test_reenabled_conductor_resumes(test_db):
    _mk_setup()
    cond = conductor.get_or_create_conductor()
    forge_services.update_agent(cond["id"], conductor_active=False)
    forge_services.update_agent(cond["id"], conductor_active=True)
    calls = []
    with patch.object(forge_services, "send_runtime_message",
                      lambda *a, **k: calls.append(k)):
        result = conductor.run_planning_turn()
    assert result["projects"][0]["ok"] is True
    assert len(calls) == 1
