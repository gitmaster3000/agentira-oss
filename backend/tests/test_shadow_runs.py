"""Shadow runs — eager infrastructure, lazy visibility (AP-151).

Every task chat dispatch reserves a Run row at trigger-time (so the agent can
register artifacts and the daemon can capture logs/diagnostics). At
complete_trigger:

  - work crystallized (diff / artifact / finish_run) -> keep the Run
  - no work -> delete the Run; AgentMessage rows lose their run_id link but
    survive in the chat thread via scope_key + trace_id.

These tests guard:
  - shadow Run created for a task chat (env vars, log_dir, worktree fields)
  - non-task chats DON'T create shadows
  - explicit run_id (Run button / D-routing resume) doesn't create a shadow
  - shadow with diff is kept
  - shadow with artifact is kept
  - shadow with agent-declared outcome is kept
  - shadow with NONE of the above is deleted at complete_trigger
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
    Agent as ForgeAgent, ForgeRuntime, RuntimeStatus,
    AgentMessage, Run, RunStatus, RunOutcome,
)


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


def _setup_agent_in_task():
    """Returns dict with agent_id, task_id, project_id of a claude-runtime
    agent ready for chat dispatches."""
    with forge_services._session() as db:
        rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                          status=RuntimeStatus.ONLINE)
        db.add(rt); db.commit(); rt_id = rt.id
    project = core_services.create_project("Shadow Test", actor="system")
    task = core_services.create_task(project["id"], "do thing", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    return {"agent_id": agent["id"], "task_id": task["id"],
            "project_id": project["id"], "rt_id": rt_id}


# ── dispatch_trigger: shadow reservation ─────────────────────────────────

@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_chat_in_task_scope_creates_shadow_run():
    s = _setup_agent_in_task()
    res = forge_services.dispatch_trigger(
        s["agent_id"], "hello", kind="chat",
        scope_key=f"task:{s['task_id']}",
    )
    assert res.get("ok") is True
    # The dispatch's run_id should be the shadow we reserved.
    assert res.get("run_id"), "shadow run_id must be returned"

    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == res["run_id"]).first()
        assert r is not None
        assert r.trigger_event == "chat.shadow"
        assert r.task_id == s["task_id"]
        assert r.project_id == s["project_id"]
        assert r.status == RunStatus.RUNNING
        assert r.started_at is not None
        assert r.worktree_path, "shadow must stamp worktree_path"
        assert r.worktree_branch, "shadow must stamp worktree_branch"
        assert r.log_dir, "shadow must stamp log_dir"

        # The user message gets linked to the shadow run.
        msg = (db.query(AgentMessage)
                 .filter(AgentMessage.scope_key == f"task:{s['task_id']}")
                 .first())
        assert msg.run_id == res["run_id"]


@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_chat_in_non_task_scope_does_not_create_shadow():
    """A `chat:default` or `chat:project:X` dispatch must NOT create a shadow
    — there's no task for it to attach to."""
    s = _setup_agent_in_task()
    res = forge_services.dispatch_trigger(
        s["agent_id"], "hi there", kind="chat", scope_key="chat:default",
    )
    assert res.get("ok") is True
    assert not res.get("run_id"), "no run_id for non-task chat"
    with forge_services._session() as db:
        runs = db.query(Run).all()
        assert runs == [], "no Run row should exist"


@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_explicit_run_id_does_not_create_shadow():
    """If a Run button dispatch (or D-routing resume) passes run_id, the
    shadow logic must not run."""
    s = _setup_agent_in_task()
    # Pre-create a real run as if from prepare_task_run.
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
        # Only the real run we pre-created — no shadow.
        assert len(runs) == 1 and runs[0].trigger_event == "task.scheduled"


# ── complete_trigger: keep vs delete ─────────────────────────────────────

def _spawn_shadow_run(s):
    """Helper: dispatch a chat into the task and return the shadow run_id."""
    with patch("backend.forge.services._dispatch_coro",
               MagicMock(return_value=None)):
        res = forge_services.dispatch_trigger(
            s["agent_id"], "hello", kind="chat",
            scope_key=f"task:{s['task_id']}",
        )
    return res["run_id"], res["trace_id"]


def test_shadow_with_no_work_is_deleted_at_complete():
    s = _setup_agent_in_task()
    run_id, trace_id = _spawn_shadow_run(s)

    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id=trace_id, run_id=run_id,
        success=True, input_tokens=10, output_tokens=5,
        work_signal={"tracked": False, "untracked": False, "committed": False},
    )

    with forge_services._session() as db:
        assert db.query(Run).filter(Run.id == run_id).first() is None, \
            "trivial shadow must be deleted"
        # AgentMessage rows survive with run_id NULL'd.
        msg = (db.query(AgentMessage)
                 .filter(AgentMessage.trace_id == trace_id).first())
        assert msg is not None, "transcript must persist"
        assert msg.run_id is None, "run_id link must be severed"


def test_shadow_with_diff_is_kept():
    s = _setup_agent_in_task()
    run_id, trace_id = _spawn_shadow_run(s)

    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id=trace_id, run_id=run_id,
        success=True, input_tokens=10, output_tokens=5,
        diff_stat="1 file changed", diff="diff --git a/x b/x\n+new",
        work_signal={"tracked": True, "untracked": False, "committed": False},
    )

    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        assert r is not None, "shadow with work must be kept"
        assert r.diff_stat == "1 file changed"
        assert r.outcome == RunOutcome.SUCCEEDED


def test_shadow_with_artifact_is_kept():
    """If the agent called register_run_artifact during the turn, the shadow
    survives even without a diff."""
    s = _setup_agent_in_task()
    run_id, trace_id = _spawn_shadow_run(s)
    # Simulate `register_run_artifact` during the turn — set artifacts_json.
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
        assert r is not None, "shadow with artifacts must be kept"


def test_shadow_with_agent_outcome_is_kept():
    """The agent called finish_run during the turn — even if no diff and no
    artifacts, the explicit verdict means it's a real run (e.g.
    `needs_input` after the agent answered a question)."""
    s = _setup_agent_in_task()
    run_id, trace_id = _spawn_shadow_run(s)
    # Simulate finish_run during the turn — set outcome explicitly.
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
        assert r is not None, "shadow with explicit verdict must be kept"
        assert r.outcome == RunOutcome.NEEDS_INPUT
