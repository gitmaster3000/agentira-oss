"""Conductor turns v2 — isolated, per-project, auditable (2026-07-22).

Every Conductor turn (planning, progress check, sprint review) is now
per-project: one PlanningTurn record per project, its own `turn:{id}`
conversation scope, and facts that never mix another project's tasks in.
`chat:default` is never used by the Conductor's per-project turns.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge import conductor
from backend.forge.models import Agent, ForgeRuntime, Run, RunOutcome, RunStatus


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
    rt = ForgeRuntime(id=uuid.uuid4().hex[:12], daemon_id=uuid.uuid4().hex[:8],
                      provider="claude", binary_path="/bin/claude",
                      status="online")
    db.add(rt)
    db.commit()
    return rt.id


def _mk_project_with_agent(name: str):
    """One conductor-enabled agent + project + an unassigned todo task
    (so the project has plannable work), returns (agent_id, project_id,
    task_id)."""
    bot = core_services.create_service_account(f"bot-{name}")
    proj = core_services.create_project(name)
    from backend.models import Task, Status, Profile
    with forge_services._session() as db:
        rt_id = _mk_runtime(db)
        prof = db.get(Profile, bot["id"])
        prof.default_project_id = proj["id"]
        prof.conductor_enabled = True
        prof.runtime_id = rt_id
        a = Agent(id=bot["id"], profile_id=bot["id"], name=f"bot-{name}",
                  executor_type="http", model="", runtime_id=rt_id)
        db.add(a)
        todo = db.query(Status).filter(Status.name == "todo").first()
        t = Task(project_id=proj["id"], key=f"{name}-1",
                 title=f"Task for {name}", description="", status_id=todo.id,
                 assignee="")
        db.add(t)
        db.commit()
        return a.id, proj["id"], t.id


# ── A: one PlanningTurn per project, isolated facts, own scope key ──────

def test_planning_turn_per_project_isolated_scopes(test_db):
    _, project_a, task_a = _mk_project_with_agent("Alpha")
    _, project_b, task_b = _mk_project_with_agent("Bravo")
    conductor.get_or_create_conductor()

    with patch.object(forge_services, "send_runtime_message",
                      return_value={"ok": True}):
        result = conductor.run_planning_turn()

    projects = {r["project_id"]: r for r in result["projects"]}
    assert set(projects) == {project_a, project_b}
    assert all(r["ok"] for r in projects.values())

    turns = conductor.get_recent_planning_turns(limit=10)
    turns_by_project = {
        t["facts_snapshot"]["project_id"]: t for t in turns
        if t["trigger"] == "cron"
    }
    assert set(turns_by_project) == {project_a, project_b}

    turn_a = turns_by_project[project_a]
    turn_b = turns_by_project[project_b]

    # Each turn's own scope key is turn:{its own id} — never chat:default.
    assert turn_a["conversation_scope_key"] == f"turn:{turn_a['id']}"
    assert turn_b["conversation_scope_key"] == f"turn:{turn_b['id']}"
    assert turn_a["conversation_scope_key"] != turn_b["conversation_scope_key"]

    # Isolation: project A's facts never mention project B's task, and
    # vice versa.
    a_task_ids = {t["id"] for t in turn_a["facts_snapshot"]["unassigned_tasks"]}
    b_task_ids = {t["id"] for t in turn_b["facts_snapshot"]["unassigned_tasks"]}
    assert task_a in a_task_ids and task_b not in a_task_ids
    assert task_b in b_task_ids and task_a not in b_task_ids


def test_chat_default_never_used_by_planning_turn(test_db):
    _mk_project_with_agent("Solo")
    conductor.get_or_create_conductor()
    calls = []

    def fake_send(agent_id, *, content, scope_key=None, **kw):
        calls.append(scope_key)
        return {"ok": True}

    with patch.object(forge_services, "send_runtime_message", fake_send):
        conductor.run_planning_turn()

    assert calls, "expected a dispatch"
    assert "chat:default" not in calls
    assert all(sk.startswith("turn:") for sk in calls)


# ── progress check: per-project, records PlanningTurn, skip token-free ──

def test_progress_check_records_planning_turn_per_project(test_db):
    agent_id, project_id, task_id = _mk_project_with_agent("Charlie")
    from backend.models import Task, Status
    with forge_services._session() as db:
        ip = db.query(Status).filter(Status.name == "in_progress").first()
        db.query(Task).filter(Task.id == task_id).update(
            {"status_id": ip.id, "assignee": "bot-Charlie"})
        db.commit()
        db.add(Run(agent_id=agent_id, task_id=task_id, project_id=project_id,
                   status=RunStatus.FAILED, outcome=RunOutcome.FAILED,
                   error="boom", last_heartbeat_at=datetime.now(timezone.utc)))
        db.commit()
    conductor.get_or_create_conductor()

    with patch.object(forge_services, "send_runtime_message",
                      return_value={"ok": True}) as mocked:
        result = conductor.run_progress_check_turn()

    assert mocked.called
    proj_result = next(r for r in result["projects"]
                       if r["project_id"] == project_id)
    assert proj_result["ok"] is True

    turns = conductor.get_recent_planning_turns(limit=10)
    turn = next(t for t in turns if t["trigger"] == "progress_check")
    assert turn["status"] == "dispatched"
    assert turn["conversation_scope_key"] == f"turn:{turn['id']}"


def test_progress_check_skip_path_is_token_free(test_db):
    _mk_project_with_agent("Delta")  # no in_progress/review tasks at all
    conductor.get_or_create_conductor()
    calls = []
    with patch.object(forge_services, "send_runtime_message",
                      lambda *a, **k: calls.append(k)):
        result = conductor.run_progress_check_turn()
    assert calls == []
    assert all(r.get("skipped") == "nothing_stalled" for r in result["projects"])


# ── backlog_candidates: ordering + cap ───────────────────────────────────

def test_backlog_candidates_ordering_and_cap(test_db):
    from backend.forge.repos import tasks as tasks_repo
    from backend.models import Task, Status
    _, project_id, _ = _mk_project_with_agent("Echo")
    with forge_services._session() as db:
        backlog = db.query(Status).filter(Status.name == "backlog").first()
        base = datetime.now(timezone.utc)
        ids_in_order = []
        for i in range(5):
            t = Task(project_id=project_id, key=f"Echo-b{i}", title=f"b{i}",
                     description="", status_id=backlog.id, assignee="",
                     created_at=base + timedelta(minutes=i))
            db.add(t)
            db.flush()
            ids_in_order.append(t.id)
        db.commit()
        rows = tasks_repo.backlog_candidates(
            db, project_id=project_id, status_id=backlog.id, limit=3)
    assert [r.id for r in rows] == ids_in_order[:3]


# ── sprint review ────────────────────────────────────────────────────────

def test_sprint_review_skips_when_digest_empty(test_db):
    _mk_project_with_agent("Foxtrot")  # no runs -> empty 24h digest
    conductor.get_or_create_conductor()
    calls = []
    with patch.object(forge_services, "send_runtime_message",
                      lambda *a, **k: calls.append(k)):
        result = conductor.run_sprint_review_turn()
    assert calls == []
    assert all(r.get("skipped") == "empty_digest" for r in result["projects"])


def test_sprint_review_dispatches_with_own_scope_and_record(test_db):
    agent_id, project_id, task_id = _mk_project_with_agent("Golf")
    with forge_services._session() as db:
        db.add(Run(agent_id=agent_id, task_id=task_id, project_id=project_id,
                   status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                   finished_at=datetime.now(timezone.utc)))
        db.commit()
    conductor.get_or_create_conductor()
    calls = []

    def fake_send(agent_id_, *, content, scope_key=None, **kw):
        calls.append({"content": content, "scope_key": scope_key})
        return {"ok": True}

    with patch.object(forge_services, "send_runtime_message", fake_send):
        result = conductor.run_sprint_review_turn()

    proj_result = next(r for r in result["projects"]
                       if r["project_id"] == project_id)
    assert proj_result["ok"] is True
    assert len(calls) == 1
    assert calls[0]["scope_key"] == f"turn:{proj_result['turn_id']}"
    assert "SPRINT REVIEW" in calls[0]["content"]

    turns = conductor.get_recent_planning_turns(limit=10)
    turn = next(t for t in turns if t["trigger"] == "sprint_review")
    assert turn["status"] == "dispatched"
    assert turn["conversation_scope_key"] == f"turn:{turn['id']}"
