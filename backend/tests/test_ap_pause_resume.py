"""Pause/resume correctness.

Pausing a run can't freeze a live claude process (SIGSTOP corrupts its
streaming sockets), so the daemon terminates the subprocess instead. That
makes pause/resume a *park + relaunch*, not a suspend + continue:

  - pause   → SIGTERM the subprocess; the daemon reports back paused=True
              ONLY to hand the backend the session_id. Run stays PAUSED.
  - resume  → re-dispatch a fresh process that reloads the conversation
              from the captured session via `claude --resume`.

A paused run must never read as FAILED, and a resumed run must actually
relaunch (not flip to a process-less zombie RUNNING).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import patch

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    Agent, ForgeRuntime, RuntimeStatus, Run, RunStatus,
    AgentMessage, MessageRole, Conversation,
)


@pytest.fixture(autouse=True)
def test_db(pg):
    yield bdb.SessionLocal


def _seed_runtime(TestSession) -> str:
    """A claude runtime that advertises the `resume` capability — required
    for dispatch_pending_run to thread resume_session_id through."""
    db = TestSession()
    rt = ForgeRuntime(daemon_id="d", provider="claude",
                      binary_path="/tmp/claude", status=RuntimeStatus.ONLINE,
                      capabilities=json.dumps(["resume"]))
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    return rt_id


class _FakeHub:
    def __init__(self):
        self.calls: list[dict] = []

    async def dispatch_trigger(self, **kwargs):
        self.calls.append(kwargs)


def _drive(fn):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = fn()
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        return result
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _mk_task_agent(TestSession):
    rt_id = _seed_runtime(TestSession)
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "Build the thing",
                                     actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    return task["id"], agent["id"]


def _mk_paused_run(TestSession, task_id, agent_id):
    """A run prepared then forced to PAUSED — what a SIGTERM'd pause leaves."""
    prepared = forge_services.prepare_task_run(task_id=task_id, agent_id=agent_id)
    run_id = prepared["id"]
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        r.status = RunStatus.PAUSED
        db.commit()
    return run_id


# ── paused trigger-complete ────────────────────────────────────────────

def test_paused_complete_keeps_run_paused_and_stores_session(test_db):
    """The daemon's paused post must NOT complete the run — it stays
    PAUSED — and the session_id is persisted for a later resume."""
    task_id, agent_id = _mk_task_agent(test_db)
    run_id = _mk_paused_run(test_db, task_id, agent_id)
    scope = f"task:{task_id}"
    forge_services._TRACE_SCOPE["tp"] = scope
    try:
        forge_services.complete_trigger(
            agent_id=agent_id, trace_id="tp", run_id=run_id,
            success=False, error="subprocess exited with code 1",
            session_id="sess-abc123", paused=True,
        )
    finally:
        forge_services._TRACE_SCOPE.pop("tp", None)

    run = forge_services.get_run(run_id)
    assert run["status"] == "paused", run["status"]
    # Session persisted both on the run and on the scope's conversation.
    assert forge_services.get_runtime_session(
        agent_id=agent_id, scope_key=scope) == "sess-abc123"
    with forge_services._session() as db:
        assert db.get(Run, run_id).session_id == "sess-abc123"


def test_paused_complete_posts_no_failure_message(test_db):
    """A paused run is not a failure — no scary '⚠ execution failed'
    message should land in the chat."""
    task_id, agent_id = _mk_task_agent(test_db)
    run_id = _mk_paused_run(test_db, task_id, agent_id)
    forge_services._TRACE_SCOPE["tp2"] = f"task:{task_id}"
    try:
        forge_services.complete_trigger(
            agent_id=agent_id, trace_id="tp2", run_id=run_id,
            success=False, error="subprocess exited with code 1",
            session_id="sess-x", paused=True,
        )
    finally:
        forge_services._TRACE_SCOPE.pop("tp2", None)
    with forge_services._session() as db:
        sysmsgs = (db.query(AgentMessage)
                   .filter(AgentMessage.role == MessageRole.SYSTEM)
                   .all())
    assert not any("execution failed" in m.content for m in sysmsgs)


# ── resume ─────────────────────────────────────────────────────────────

def test_resume_run_redispatches_with_resume_session(test_db):
    """Resume relaunches the run: one trigger fired, status flips
    PAUSED → RUNNING, and the captured session rides as resume_session_id
    so claude --resume reloads the conversation."""
    task_id, agent_id = _mk_task_agent(test_db)
    run_id = _mk_paused_run(test_db, task_id, agent_id)
    scope = f"task:{task_id}"
    forge_services.upsert_conversation(
        agent_id=agent_id, scope_key=scope, runtime_session_id="sess-resume-1")

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        result = _drive(lambda: forge_services.resume_run(run_id))

    assert "error" not in result, result
    assert len(fake.calls) == 1, "resume must dispatch exactly one trigger"
    assert fake.calls[0]["run_id"] == run_id
    assert fake.calls[0]["resume_session_id"] == "sess-resume-1"
    assert forge_services.get_run(run_id)["status"] == "running"


def test_resume_sends_continuation_nudge_not_task_prompt(test_db):
    """Resume must send a short 'continue' nudge — re-sending the full
    task prompt would make the agent restart. initial_prompt is untouched."""
    task_id, agent_id = _mk_task_agent(test_db)
    run_id = _mk_paused_run(test_db, task_id, agent_id)
    original_prompt = forge_services.get_run(run_id)["initial_prompt"]

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        _drive(lambda: forge_services.resume_run(run_id))

    dispatched = fake.calls[0]["prompt"]
    assert dispatched == forge_services._resume_continuation_prompt()
    assert "# Task:" not in dispatched
    # The stored task prompt is preserved, not overwritten by the nudge.
    assert forge_services.get_run(run_id)["initial_prompt"] == original_prompt


def test_resume_rejects_non_paused_run(test_db):
    """Only PAUSED runs can be resumed — a READY run is not resumable."""
    task_id, agent_id = _mk_task_agent(test_db)
    prepared = forge_services.prepare_task_run(task_id=task_id, agent_id=agent_id)
    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        result = _drive(lambda: forge_services.resume_run(prepared["id"]))
    assert "error" in result
    assert fake.calls == []
