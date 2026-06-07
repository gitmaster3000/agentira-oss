"""Run emergence — work is audited, chat is cheap (AP-178).

Every task-chat dispatch reserves a real Run row at trigger-time (so the agent
can register artifacts and the daemon can capture logs/diagnostics). The row is
never deleted. At complete_trigger:

  - the turn did work (diff / artifact / finish_run outcome) -> is_work=True,
    so it surfaces in the Runs list as a "Run".
  - the turn was just talk -> is_work=False; the row + its messages are kept
    (transcript intact), the UI keeps it as chat.

Replaces the old shadow create-then-delete/promote dance (test_shadow_runs.py)
and the lazy-crystallize path (test_turns_crystallize.py).

These tests guard:
  - a task chat reserves a run (is_work=False, RUNNING, worktree/log_dir stamped)
  - non-task chats reserve no run
  - explicit run_id (Run button / resume) doesn't reserve a chat run, is_work=True
  - a talk-only turn stays is_work=False, keeps its messages, is hidden from list_runs
  - diff / artifact / finish_run outcome each flip is_work=True and surface it
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    ForgeRuntime, RuntimeStatus, AgentMessage, Run, RunStatus, RunOutcome,
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
         patch("backend.forge.msg_queue.SessionLocal", TestSession), \
         patch("backend.forge.conductor.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _setup_agent_in_task():
    with forge_services._session() as db:
        rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                          status=RuntimeStatus.ONLINE)
        db.add(rt); db.commit(); rt_id = rt.id
    project = core_services.create_project("Emergence Test", actor="system")
    task = core_services.create_task(project["id"], "do thing", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    return {"agent_id": agent["id"], "task_id": task["id"],
            "project_id": project["id"], "rt_id": rt_id}


def _spawn_chat_run(s):
    """Dispatch a chat into the task; return (run_id, trace_id)."""
    with patch("backend.forge.services._dispatch_coro",
               MagicMock(return_value=None)):
        res = forge_services.dispatch_trigger(
            s["agent_id"], "hello", kind="chat",
            scope_key=f"task:{s['task_id']}",
        )
    return res["run_id"], res["trace_id"]


# ── dispatch_trigger: run reservation ────────────────────────────────────

@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_chat_in_task_scope_reserves_run_is_work_false():
    s = _setup_agent_in_task()
    res = forge_services.dispatch_trigger(
        s["agent_id"], "hello", kind="chat",
        scope_key=f"task:{s['task_id']}",
    )
    assert res.get("ok") is True
    assert res.get("run_id"), "a run_id must be reserved"

    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == res["run_id"]).first()
        assert r is not None
        assert r.trigger_event == "chat"
        assert r.is_work is False, "a fresh chat run starts is_work=False"
        assert r.task_id == s["task_id"]
        assert r.project_id == s["project_id"]
        assert r.status == RunStatus.RUNNING
        assert r.started_at is not None
        assert r.worktree_path and r.worktree_branch and r.log_dir

        msg = (db.query(AgentMessage)
                 .filter(AgentMessage.scope_key == f"task:{s['task_id']}")
                 .first())
        assert msg.run_id == res["run_id"], "user message links to the run"


@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_chat_in_non_task_scope_reserves_no_run():
    s = _setup_agent_in_task()
    res = forge_services.dispatch_trigger(
        s["agent_id"], "hi there", kind="chat", scope_key="chat:default",
    )
    assert res.get("ok") is True
    assert not res.get("run_id"), "no run for non-task chat"
    with forge_services._session() as db:
        assert db.query(Run).all() == [], "no Run row should exist"


@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_explicit_run_id_reuses_run_and_is_work_true():
    s = _setup_agent_in_task()
    real = forge_services.create_run(
        agent_id=s["agent_id"], task_id=s["task_id"],
        project_id=s["project_id"], trigger_event="task.scheduled",
    )
    res = forge_services.dispatch_trigger(
        s["agent_id"], "continue", kind="run_step", run_id=real["id"],
        scope_key=f"task:{s['task_id']}",
    )
    assert res["run_id"] == real["id"], "must use the passed run_id"
    with forge_services._session() as db:
        runs = db.query(Run).all()
        assert len(runs) == 1, "no extra run reserved"
        assert runs[0].trigger_event == "task.scheduled"
        assert runs[0].is_work is True, "explicit runs surface immediately"


# ── complete_trigger: is_work decision ───────────────────────────────────

def test_talk_only_turn_stays_is_work_false_and_keeps_messages():
    s = _setup_agent_in_task()
    run_id, trace_id = _spawn_chat_run(s)

    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id=trace_id, run_id=run_id,
        success=True, input_tokens=10, output_tokens=5,
        work_signal={"tracked": False, "untracked": False, "committed": False},
    )

    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        assert r is not None, "the run row is never deleted"
        assert r.is_work is False, "talk-only turn stays is_work=False"
        msg = (db.query(AgentMessage)
                 .filter(AgentMessage.trace_id == trace_id).first())
        assert msg is not None and msg.run_id == run_id, \
            "transcript persists and keeps its run_id (no survival hack)"

    # Hidden from the global runs list, visible to the per-task lookup (so the
    # chat Stop button can still find it while in flight).
    assert not any(v["id"] == run_id
                   for v in forge_services.list_runs(agent_id=s["agent_id"])), \
        "is_work=False run must not pollute the Runs list"
    assert any(v["id"] == run_id
               for v in forge_services.list_runs_for_task(s["task_id"])), \
        "per-task lookup still sees it"


def test_turn_with_diff_becomes_work_and_surfaces():
    s = _setup_agent_in_task()
    run_id, trace_id = _spawn_chat_run(s)

    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id=trace_id, run_id=run_id,
        success=True, input_tokens=10, output_tokens=5,
        diff_stat="1 file changed", diff="diff --git a/x b/x\n+new",
        work_signal={"tracked": True, "untracked": False, "committed": False},
    )

    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        assert r is not None and r.is_work is True
        assert r.trigger_event == "chat", "trigger stays 'chat' — no promote flip"
    assert any(v["id"] == run_id
               for v in forge_services.list_runs(agent_id=s["agent_id"])), \
        "a work turn surfaces in the Runs list"


def test_turn_with_artifact_becomes_work():
    s = _setup_agent_in_task()
    run_id, trace_id = _spawn_chat_run(s)
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        r.artifacts_json = '[{"kind":"pr","url":"https://example/pr/1","label":"PR"}]'
        db.commit()

    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id=trace_id, run_id=run_id,
        success=True, input_tokens=5, output_tokens=5,
        work_signal={"tracked": False, "untracked": False, "committed": False},
    )

    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        assert r is not None and r.is_work is True


def test_finish_run_on_chat_run_posts_no_run_activity():
    """A chat turn's finish_run must NOT post a 'Run {outcome}' activity comment
    (that made an @mention comment look like it produced a run). An explicit
    (task.scheduled) run still posts its verdict to the feed."""
    from backend.models import Activity
    s = _setup_agent_in_task()
    chat_run_id, _ = _spawn_chat_run(s)
    forge_services.finish_run(chat_run_id, outcome="blocked", summary="need info")

    exp = forge_services.create_run(
        agent_id=s["agent_id"], task_id=s["task_id"],
        project_id=s["project_id"], trigger_event="task.scheduled")
    forge_services.finish_run(exp["id"], outcome="blocked", summary="need info")

    with forge_services._session() as db:
        bodies = [a.detail or "" for a in
                  db.query(Activity).filter(Activity.task_id == s["task_id"],
                                            Activity.action == "commented").all()]
    assert not any(chat_run_id[:8] in b for b in bodies), \
        "a chat run's finish_run must not post a 'Run' activity"
    assert any(exp["id"][:8] in b for b in bodies), \
        "an explicit run's finish_run still posts its verdict"


def test_turn_with_agent_outcome_becomes_work():
    s = _setup_agent_in_task()
    run_id, trace_id = _spawn_chat_run(s)
    # Simulate finish_run during the turn — set the outcome on the run row.
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        r.outcome = RunOutcome.NEEDS_INPUT
        r.summary = "Need API key"
        db.commit()

    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id=trace_id, run_id=run_id,
        success=True, input_tokens=5, output_tokens=5,
        work_signal={"tracked": False, "untracked": False, "committed": False},
    )

    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        assert r is not None and r.is_work is True
        assert r.outcome == RunOutcome.NEEDS_INPUT
