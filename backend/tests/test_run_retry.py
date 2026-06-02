"""Explicit `services.retry_run` — Restart button backend.

AP-120 already retries when a user chats into a task whose latest run
failed. This is the *explicit* button-driven path.

Verifies:
- A FAILED run with a task → retry creates a new run for the same
  (task, agent) and drops a SYSTEM breadcrumb.
- A CANCELLED run is also retryable.
- A SUCCEEDED run is retryable (re-do the work).
- An IN-FLIGHT run (RUNNING / PAUSED / PENDING) is refused.
- A run with no task_id (free chat) is refused.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    Agent, Run, RunStatus, RunOutcome, AgentMessage, MessageRole,
    ForgeRuntime, RuntimeStatus,
)
from backend.models import Profile  # noqa: F401 — registers mapper


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.conductor.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _seed_runtime(TestSession):
    with TestSession() as db:
        rt = ForgeRuntime(daemon_id="d1", provider="claude",
                          binary_path="/x", status=RuntimeStatus.ONLINE)
        db.add(rt); db.commit(); return rt.id


def _make_run(TestSession, *, status=RunStatus.FAILED, outcome=RunOutcome.FAILED,
              task_id="t1") -> Run:
    rt_id = _seed_runtime(TestSession)
    agent = forge_services.create_agent(
        name="A", executor_type="cli", runtime_id=rt_id,
    )
    p = core_services.create_project("P", actor="system")
    if task_id == "t1":
        t = core_services.create_task(p["id"], "Do thing", actor="system")
        task_id = t["id"]
    with TestSession() as db:
        r = Run(agent_id=agent["id"], task_id=task_id,
                project_id=p["id"], trigger_event="task.scheduled",
                status=status, outcome=outcome,
                model_used="claude-sonnet-4-6")
        db.add(r); db.commit(); db.refresh(r)
        return r.id, agent["id"], task_id


def test_retry_failed_run_schedules_new_run(test_db):
    run_id, agent_id, task_id = _make_run(test_db)
    # schedule_task_run hits the live dispatch path; stub it so the test
    # is pure unit. The stub just records what was passed.
    captured = {}
    def _stub(*, task_id, agent_id, extra_context=""):
        captured.update({"task_id": task_id, "agent_id": agent_id,
                          "extra_context": extra_context})
        return {"ok": True, "id": "new-run-id", "run_id": "new-run-id"}
    with patch("backend.forge.services.schedule_task_run", _stub):
        result = forge_services.retry_run(run_id)
    assert result.get("ok") is True
    assert captured["task_id"] == task_id
    assert captured["agent_id"] == agent_id
    assert run_id in captured["extra_context"]
    # System breadcrumb landed on the task scope.
    with test_db() as db:
        msgs = db.query(AgentMessage).filter(
            AgentMessage.scope_key == f"task:{task_id}",
            AgentMessage.role == MessageRole.SYSTEM,
        ).all()
        assert any("Restarted from run" in m.content for m in msgs)


def test_retry_cancelled_run_is_allowed(test_db):
    run_id, *_ = _make_run(test_db, status=RunStatus.CANCELLED,
                            outcome=RunOutcome.FAILED)
    with patch("backend.forge.services.schedule_task_run",
                return_value={"ok": True, "id": "new"}):
        assert "error" not in forge_services.retry_run(run_id)


def test_retry_succeeded_run_is_allowed(test_db):
    run_id, *_ = _make_run(test_db, status=RunStatus.COMPLETED,
                            outcome=RunOutcome.SUCCEEDED)
    with patch("backend.forge.services.schedule_task_run",
                return_value={"ok": True, "id": "new"}):
        assert "error" not in forge_services.retry_run(run_id)


@pytest.mark.parametrize("status", [RunStatus.RUNNING, RunStatus.PENDING,
                                      RunStatus.PAUSED])
def test_retry_inflight_run_is_refused(test_db, status):
    run_id, *_ = _make_run(test_db, status=status, outcome=None)
    out = forge_services.retry_run(run_id)
    assert "error" in out
    assert status.value in out["error"]


def test_retry_free_chat_run_is_refused(test_db):
    # A run with task_id = None (free-floating chat shadow that escaped
    # cleanup, hypothetically). Force-construct it.
    rt_id = _seed_runtime(test_db)
    agent = forge_services.create_agent(
        name="A", executor_type="cli", runtime_id=rt_id,
    )
    with test_db() as db:
        r = Run(agent_id=agent["id"], task_id=None, project_id=None,
                trigger_event="chat.shadow", status=RunStatus.FAILED,
                outcome=RunOutcome.FAILED, model_used="x")
        db.add(r); db.commit(); db.refresh(r)
        rid = r.id
    out = forge_services.retry_run(rid)
    assert "error" in out
    assert "free-floating" in out["error"]


def test_retry_unknown_run_returns_not_found(test_db):
    out = forge_services.retry_run("does-not-exist")
    assert out == {"error": "run_not_found"}
