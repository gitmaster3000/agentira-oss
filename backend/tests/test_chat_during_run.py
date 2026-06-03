"""Chat-during-run: queue, then resume (AP-179).

- A message into a RUNNING run is QUEUED — the running turn is NOT interrupted.
  The queued message dispatches FIFO when the run reaches a terminal state.
- A message into a PAUSED or parked (needs_input/blocked) run resumes it,
  carrying its run_id so it continues the episode (no duplicate run).

Replaces the old park-on-pending_steer + pause-and-fold steering model.
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
from backend.forge import msg_queue
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
         patch("backend.forge.runs.SessionLocal", TestSession), \
         patch("backend.forge.msg_queue.SessionLocal", TestSession):
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
def test_message_during_running_run_is_queued_not_interrupted(test_db):
    s = _setup(test_db)
    run_id = _mk_run(s, RunStatus.RUNNING)
    scope = f"task:{s['task_id']}"

    res = forge_services.send_runtime_message(
        s["agent_id"], content="actually use postgres", scope_key=scope)

    assert res.get("queued_id"), "message must be queued"
    # The running turn is NOT interrupted — it keeps running.
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        assert r.status == RunStatus.RUNNING
    # The queue holds the message for the UI's pills.
    queued = msg_queue.list_for_scope(agent_id=s["agent_id"], scope_key=scope)
    assert len(queued) == 1 and queued[0]["content"] == "actually use postgres"


@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_queued_message_dispatches_on_terminal(test_db):
    s = _setup(test_db)
    run_id = _mk_run(s, RunStatus.RUNNING)
    scope = f"task:{s['task_id']}"
    forge_services.send_runtime_message(
        s["agent_id"], content="do X next", scope_key=scope)
    assert msg_queue.list_for_scope(agent_id=s["agent_id"], scope_key=scope)

    # The running turn completes → the queued message is dispatched (FIFO),
    # draining the queue.
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t1", run_id=run_id,
        success=True, input_tokens=1, output_tokens=1,
    )
    assert msg_queue.list_for_scope(agent_id=s["agent_id"], scope_key=scope) == [], \
        "queue must drain when the turn reaches a terminal state"


@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_queued_message_survives_discard_then_dispatches(test_db):
    """A queued message is keyed to the conversation, not the run — discarding
    the active run still flushes the queue afterward."""
    s = _setup(test_db)
    run_id = _mk_run(s, RunStatus.RUNNING)
    scope = f"task:{s['task_id']}"
    forge_services.send_runtime_message(
        s["agent_id"], content="follow-up", scope_key=scope)

    # Daemon confirms a discard (cancel) of the running run.
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t1", run_id=run_id,
        success=False, cancelled=True,
    )
    assert msg_queue.list_for_scope(agent_id=s["agent_id"], scope_key=scope) == [], \
        "queued message dispatches even though its run was discarded"


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
    assert "queued_id" not in res and "resumed_run_id" not in res
