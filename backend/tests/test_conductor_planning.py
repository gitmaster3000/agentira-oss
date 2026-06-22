"""Conductor planning turn — the LLM assigns the unassigned todo backlog.

The deterministic queue tick DISPATCHES; the planning turn is the LLM
deciding WHO gets WHAT. Facts are gathered token-free; the LLM only
decides; it assigns by calling update_task (assignee). Runs only when
there is unassigned work.
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


# ── fact gathering ─────────────────────────────────────────────────────

def test_gather_planning_facts_lists_unassigned_todo(test_db):
    agent_id, _, task_id = _mk_setup()
    facts = conductor.gather_planning_facts()
    assert any(a["name"] == "bot1" for a in facts["agents"])
    assert any(t["id"] == task_id for t in facts["unassigned_tasks"])


def test_gather_planning_facts_excludes_assigned_tasks(test_db):
    agent_id, _, task_id = _mk_setup()
    from backend.models import Task
    with forge_services._session() as db:
        db.query(Task).filter(Task.id == task_id).update({"assignee": "bot1"})
        db.commit()
    facts = conductor.gather_planning_facts()
    assert task_id not in [t["id"] for t in facts["unassigned_tasks"]]


# ── run_planning_turn ──────────────────────────────────────────────────

def test_planning_skips_when_nothing_unassigned(test_db):
    # conductor-enabled agent, but no todo tasks created.
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
    calls = []
    with patch.object(forge_services, "send_runtime_message",
                      lambda *a, **k: calls.append(k)):
        result = conductor.run_planning_turn()
    assert result.get("skipped")
    assert calls == []


def test_planning_dispatches_llm_turn_when_work_exists(test_db):
    _mk_setup()
    conductor.get_or_create_conductor()  # binds the claude runtime
    calls = []

    def fake_send(agent_id, *, content, scope_key=None, **kw):
        calls.append({"agent_id": agent_id, "content": content})
        return {"ok": True}

    with patch.object(forge_services, "send_runtime_message", fake_send):
        result = conductor.run_planning_turn()

    assert result.get("ok") is True
    assert len(calls) == 1
    assert "QUEUE PLANNING" in calls[0]["content"]
    assert "Build the parser" in calls[0]["content"]
    assert "update_task" in calls[0]["content"]
    assert conductor.get_last_plan().get("ok") is True


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
    assert result.get("ok") is True
    assert len(calls) == 1
