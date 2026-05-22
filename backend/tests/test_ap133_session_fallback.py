"""AP-133: graceful resume fallback when claude can't find the session
file. Daemon detects + retries without --resume + sets session_lost=True
on the trigger-complete; backend clears the stale id from the scope's
Conversation row and posts a system message in the chat thread.
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
    AgentMessage, Conversation, ForgeRuntime, MessageRole, Run,
    RunStatus, RuntimeStatus,
)


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _setup(TestSession) -> dict:
    db = TestSession()
    rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                      status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "T", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(
        agent_id=agent["id"], task_id=task["id"], project_id=project["id"],
    )
    # Seed a Conversation with a stale runtime_session_id — the very
    # scenario AP-133 fixes.
    scope = f"task:{task['id']}"
    forge_services.upsert_conversation(
        agent_id=agent["id"], scope_key=scope,
        runtime_session_id="stale-session-abc",
    )
    return {"run_id": run["id"], "agent_id": agent["id"],
            "task_id": task["id"], "scope": scope}


# ── happy path ───────────────────────────────────────────────────────

def test_session_lost_clears_conversation_session_id(test_db):
    """The whole point: the next dispatch on this scope must NOT pick
    up the stale id again."""
    s = _setup(test_db)
    with forge_services._session() as db:
        # Pre-check: stale id is there.
        conv = (db.query(Conversation)
                  .filter_by(agent_id=s["agent_id"],
                             scope_key=s["scope"])
                  .first())
        assert conv.runtime_session_id == "stale-session-abc"

    forge_services._TRACE_SCOPE["t1"] = s["scope"]
    try:
        forge_services.complete_trigger(
            agent_id=s["agent_id"], trace_id="t1", run_id=s["run_id"],
            success=True, session_lost=True,
        )
    finally:
        forge_services._TRACE_SCOPE.pop("t1", None)

    with forge_services._session() as db:
        conv = (db.query(Conversation)
                  .filter_by(agent_id=s["agent_id"],
                             scope_key=s["scope"])
                  .first())
        assert conv.runtime_session_id == ""


def test_session_lost_posts_system_message(test_db):
    """User sees what happened — chat thread gets a system message."""
    s = _setup(test_db)
    forge_services._TRACE_SCOPE["t2"] = s["scope"]
    try:
        forge_services.complete_trigger(
            agent_id=s["agent_id"], trace_id="t2", run_id=s["run_id"],
            success=True, session_lost=True,
        )
    finally:
        forge_services._TRACE_SCOPE.pop("t2", None)
    with forge_services._session() as db:
        sys_msgs = (db.query(AgentMessage)
                      .filter(AgentMessage.agent_id == s["agent_id"],
                              AgentMessage.role == MessageRole.SYSTEM,
                              AgentMessage.scope_key == s["scope"])
                      .all())
    assert any("wasn't found" in m.content for m in sys_msgs)


# ── scope recovery ───────────────────────────────────────────────────

def test_session_lost_recovers_scope_from_messages_when_trace_scope_lost(test_db):
    """If _TRACE_SCOPE evaporated (backend restart), recover the scope
    from the trace's persisted messages."""
    s = _setup(test_db)
    # Pre-seed an AgentMessage tagged with this trace + scope so the
    # recovery path can find it.
    with forge_services._session() as db:
        db.add(AgentMessage(
            agent_id=s["agent_id"], trace_id="t3", scope_key=s["scope"],
            role=MessageRole.USER, content="x",
        ))
        db.commit()

    # No _TRACE_SCOPE entry — force the message-based fallback.
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t3", run_id=s["run_id"],
        success=True, session_lost=True,
    )
    with forge_services._session() as db:
        conv = (db.query(Conversation)
                  .filter_by(agent_id=s["agent_id"],
                             scope_key=s["scope"])
                  .first())
        assert conv.runtime_session_id == ""


# ── interplay with other branches ────────────────────────────────────

def test_session_lost_on_cancelled_path_still_clears(test_db):
    """Even when the run was cancelled, session_lost=True clears the
    stale id so the next reuse of this scope doesn't repeat the bug."""
    s = _setup(test_db)
    forge_services._TRACE_SCOPE["t4"] = s["scope"]
    try:
        forge_services.complete_trigger(
            agent_id=s["agent_id"], trace_id="t4", run_id=s["run_id"],
            success=False, cancelled=True, session_lost=True,
            error="Cancelled by user.",
        )
    finally:
        forge_services._TRACE_SCOPE.pop("t4", None)
    with forge_services._session() as db:
        conv = (db.query(Conversation)
                  .filter_by(agent_id=s["agent_id"],
                             scope_key=s["scope"])
                  .first())
        assert conv.runtime_session_id == ""


def test_session_lost_default_false_is_noop(test_db):
    """The default (no session_lost flag) must NOT clear anything —
    back-compat with older daemons."""
    s = _setup(test_db)
    forge_services._TRACE_SCOPE["t5"] = s["scope"]
    try:
        forge_services.complete_trigger(
            agent_id=s["agent_id"], trace_id="t5", run_id=s["run_id"],
            success=True,
        )
    finally:
        forge_services._TRACE_SCOPE.pop("t5", None)
    with forge_services._session() as db:
        conv = (db.query(Conversation)
                  .filter_by(agent_id=s["agent_id"],
                             scope_key=s["scope"])
                  .first())
        # Untouched — same stale value (or whatever upsert_conversation
        # wrote during the success path).
        assert conv.runtime_session_id == "stale-session-abc"
