"""Turn -> run model (ADR 009 / AP-136).

A standalone task chat turn that produced work crystallizes into a run; a
turn that was just talk stays a turn. Work-signal modes gate what counts.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge import turns
from backend.forge.models import (
    ForgeRuntime, Run, RunStatus, RunOutcome, RuntimeStatus,
    AgentMessage, MessageRole,
)


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession):
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


# ── work-signal mode mapping ─────────────────────────────────────────────

def test_turn_did_work_modes():
    untracked_only = {"tracked": False, "untracked": True, "committed": False}
    tracked_only = {"tracked": True, "untracked": False, "committed": False}
    committed = {"tracked": True, "untracked": False, "committed": True}
    nothing = {"tracked": False, "untracked": False, "committed": False}

    # working_tree (default): tracked OR untracked
    assert turns.turn_did_work(untracked_only, "working_tree") is True
    assert turns.turn_did_work(tracked_only, "working_tree") is True
    assert turns.turn_did_work(nothing, "working_tree") is False
    # tracked: ignores untracked-only
    assert turns.turn_did_work(untracked_only, "tracked") is False
    assert turns.turn_did_work(tracked_only, "tracked") is True
    # committed: only a commit counts
    assert turns.turn_did_work(tracked_only, "committed") is False
    assert turns.turn_did_work(committed, "committed") is True


# ── crystallization ──────────────────────────────────────────────────────

def _add_chat_turn(TestSession, s, trace_id):
    with forge_services._session() as db:
        db.add(AgentMessage(agent_id=s["agent_id"], role=MessageRole.USER,
                            content="now add tests", scope_key=f"task:{s['task_id']}",
                            trace_id=trace_id))
        db.commit()


def test_chat_turn_with_work_becomes_a_run(test_db):
    s = _setup(test_db)
    trace = uuid.uuid4().hex[:12]
    _add_chat_turn(test_db, s, trace)

    run_id = turns.maybe_crystallize_chat_turn(
        agent_id=s["agent_id"], trace_id=trace, scope_key=f"task:{s['task_id']}",
        work_signal={"tracked": True, "untracked": False, "committed": False},
        diff_stat="1 file changed", diff="diff --git a/x b/x", input_tokens=5,
    )
    assert run_id is not None
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        assert r.status == RunStatus.COMPLETED
        assert r.outcome == RunOutcome.SUCCEEDED
        assert r.task_id == s["task_id"]
        assert r.diff_stat == "1 file changed"
        # the turn's messages are backfilled onto the run
        msgs = db.query(AgentMessage).filter(AgentMessage.trace_id == trace).all()
        assert msgs and all(m.run_id == run_id for m in msgs)


def test_chat_turn_without_work_stays_a_turn(test_db):
    s = _setup(test_db)
    trace = uuid.uuid4().hex[:12]
    _add_chat_turn(test_db, s, trace)
    run_id = turns.maybe_crystallize_chat_turn(
        agent_id=s["agent_id"], trace_id=trace, scope_key=f"task:{s['task_id']}",
        work_signal={"tracked": False, "untracked": False, "committed": False},
    )
    assert run_id is None
    with forge_services._session() as db:
        assert db.query(Run).count() == 0


def test_non_task_scope_never_crystallizes(test_db):
    s = _setup(test_db)
    trace = uuid.uuid4().hex[:12]
    run_id = turns.maybe_crystallize_chat_turn(
        agent_id=s["agent_id"], trace_id=trace, scope_key="chat:default",
        work_signal={"tracked": True, "untracked": True, "committed": True},
    )
    assert run_id is None
