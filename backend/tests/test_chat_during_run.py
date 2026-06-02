"""Chat-during-run: pause / steer / resume (ADR 009 / AP-137).

- A message into a RUNNING run parks the message and pauses the run (D1);
  when the daemon confirms the pause, the parked message is dispatched as the
  next turn resuming that run.
- A message into a PAUSED or parked (needs_input/blocked) run resumes it (D2),
  carrying its run_id so it continues the episode (no duplicate run).
"""

from __future__ import annotations

import uuid
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    ForgeRuntime, Run, RunStatus, RunOutcome, RuntimeStatus,
)


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.runs.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _setup(TestSession):
    db = TestSession()
    rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                      status=RuntimeStatus.ONLINE)
    db.add(rt); db.commit(); rt_id = rt.id; db.close()
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "T", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli", runtime_id=rt_id)
    return {"task_id": task["id"], "agent_id": agent["id"], "project_id": project["id"]}


def _mk_run(s, status, outcome=None):
    with forge_services._session() as db:
        r = Run(id=uuid.uuid4().hex, agent_id=s["agent_id"], task_id=s["task_id"],
                project_id=s["project_id"], status=status, outcome=outcome)
        db.add(r); db.commit()
        return r.id


@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_message_during_running_run_parks_and_pauses(test_db):
    s = _setup(test_db)
    run_id = _mk_run(s, RunStatus.RUNNING)

    res = forge_services.send_runtime_message(
        s["agent_id"], content="actually use postgres", scope_key=f"task:{s['task_id']}")

    assert res.get("steering_run_id") == run_id
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        assert r.pending_steer == "actually use postgres"
        assert r.status == RunStatus.PAUSING  # pause_run set the transient


@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_pause_confirm_dispatches_parked_steer(test_db):
    s = _setup(test_db)
    run_id = _mk_run(s, RunStatus.PAUSING)
    with forge_services._session() as db:
        db.query(Run).filter(Run.id == run_id).update({"pending_steer": "do X instead"})
        db.commit()

    # daemon confirms the pause
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t1", run_id=run_id,
        success=False, paused=True, session_id="sess-1",
    )
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        # pending_steer consumed; the re-dispatch resumed the run → RUNNING
        assert r.pending_steer is None
        assert r.status == RunStatus.RUNNING


@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_message_resumes_needs_input_run(test_db):
    s = _setup(test_db)
    run_id = _mk_run(s, RunStatus.COMPLETED, outcome=RunOutcome.NEEDS_INPUT)

    res = forge_services.send_runtime_message(
        s["agent_id"], content="here's the API key", scope_key=f"task:{s['task_id']}")

    assert res.get("resumed_run_id") == run_id
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        assert r.status == RunStatus.RUNNING
        assert r.outcome is None  # re-opened; verdict re-declared on finish


@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_message_with_no_active_run_is_plain_chat(test_db):
    s = _setup(test_db)
    # latest run is COMPLETED+SUCCEEDED → not revived; a fresh chat turn runs
    _mk_run(s, RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED)
    res = forge_services.send_runtime_message(
        s["agent_id"], content="thanks!", scope_key=f"task:{s['task_id']}")
    assert "steering_run_id" not in res and "resumed_run_id" not in res
