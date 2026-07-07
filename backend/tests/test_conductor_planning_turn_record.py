"""AP-401: Conductor transparency — durable PlanningTurn audit records.

A planning turn's reasoning used to live only in server logs. Every
planning turn (dispatched, skipped, or errored) now persists a
`PlanningTurn` row: facts snapshot, decisions with reasons, model, and
duration. Decisions that touch a task also land on that task's activity
feed via the service layer with actor="Conductor" (AP-376 invariant).
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge import conductor
from backend.forge.models import Agent, ForgeRuntime
from backend.models import Activity


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


def _mk_setup():
    """One conductor-enabled agent + project + an unassigned todo task."""
    bot = core_services.create_service_account("bot1")
    proj = core_services.create_project("P1")
    from backend.models import Task, Status, Profile
    with forge_services._session() as db:
        rt_id = _mk_runtime(db)
        prof = db.get(Profile, bot["id"])
        prof.default_project_id = proj["id"]
        prof.conductor_enabled = True
        prof.runtime_id = rt_id
        prof.model = "claude-sonnet-4-6"
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


# ── run_planning_turn always records a durable turn ─────────────────────

def test_skip_when_nothing_to_plan_still_records_turn(test_db):
    conductor.get_or_create_conductor()
    result = conductor.run_planning_turn()
    assert result == {"skipped": "nothing to plan"}
    turns = conductor.get_recent_planning_turns()
    assert len(turns) == 1
    turn = turns[0]
    assert turn["status"] == "skipped"
    assert turn["decisions"][0]["action"] == "skipped"
    assert "nothing to plan" in turn["decisions"][0]["reason"]
    assert turn["facts_snapshot"] == {"agents": [], "unassigned_tasks": []}


def test_dispatched_turn_records_facts_model_and_scope(test_db):
    agent_id, project_id, task_id = _mk_setup()
    conductor.get_or_create_conductor()  # binds the claude runtime
    with patch.object(forge_services, "send_runtime_message",
                      return_value={"ok": True}) as mocked:
        result = conductor.run_planning_turn()
    assert mocked.called
    assert result["ok"] is True

    turns = conductor.get_recent_planning_turns()
    assert len(turns) == 1
    turn = turns[0]
    assert turn["status"] == "dispatched"
    assert turn["model"] == conductor.CONDUCTOR_DEFAULT_MODEL
    assert turn["conversation_scope_key"] == "chat:default"
    assert turn["duration_ms"] is not None
    assert any(t["id"] == task_id for t in turn["facts_snapshot"]["unassigned_tasks"])
    assert any(a["name"] == "bot1" for a in turn["facts_snapshot"]["agents"])
    assert turn["decisions"] == []  # fills in async as the LLM turn assigns


# ── decisions that touch a task also land on the task's activity feed ───

def test_record_decision_assign_and_skip_produce_full_record_and_activity(test_db):
    agent_id, project_id, task_id = _mk_setup()
    turn_id = conductor._record_planning_turn(
        trigger="cron", status="dispatched",
        facts={"agents": [], "unassigned_tasks": []}, model="claude-sonnet-4-6")
    assert turn_id is not None

    conductor.record_planning_decision(
        turn_id, action="assigned", reason="best skill match for parser work",
        task_id=task_id, agent="bot1", project_id=project_id)
    conductor.record_planning_decision(
        turn_id, action="skipped", reason="no agent available for this specialty")

    turns = conductor.get_recent_planning_turns()
    turn = next(t for t in turns if t["id"] == turn_id)
    assert len(turn["decisions"]) == 2
    assigned = turn["decisions"][0]
    assert assigned == {"action": "assigned", "task_id": task_id,
                        "agent": "bot1", "reason": "best skill match for parser work"}
    skipped = turn["decisions"][1]
    assert skipped["action"] == "skipped" and skipped["task_id"] is None

    with forge_services._session() as db:
        acts = (db.query(Activity)
                  .filter(Activity.task_id == task_id, Activity.actor == "Conductor")
                  .all())
    assert len(acts) == 1
    assert "assigned" in acts[0].detail
    assert "best skill match" in acts[0].detail


def test_get_recent_planning_turns_orders_newest_first(test_db):
    t1 = conductor._record_planning_turn(
        trigger="cron", status="skipped", facts={"agents": [], "unassigned_tasks": []})
    t2 = conductor._record_planning_turn(
        trigger="cron", status="skipped", facts={"agents": [], "unassigned_tasks": []})
    turns = conductor.get_recent_planning_turns()
    assert [t["id"] for t in turns[:2]] == [t2, t1]
