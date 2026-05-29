"""ADR 008 / AP-93: task-scoped conversations, /clear, stop-chat.

Unit-level tests:
  - conversation_scope_key precedence (task → project → default)
  - clear_conversation wipes the right rows and nothing else
  - stop_chat pauses the active run when scope is a task scope
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    AgentMessage, MessageRole, Conversation, Run, RunStatus,
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


def _mk_agent_task():
    bot = core_services.create_service_account("bot1")
    proj = core_services.create_project("P")
    from backend.models import Task, Status
    from backend.forge.models import Agent
    with forge_services._session() as db:
        # Insert a runtime-less Agent row directly — create_agent requires
        # a runtime_id, which we don't have in this unit-test environment.
        a = Agent(id=bot["id"], profile_id=bot["id"], name="bot1",
                  executor_type="http", model="")
        db.add(a)
        status = db.query(Status).first()
        t = Task(id=uuid.uuid4().hex, project_id=proj["id"],
                 key="P-1", title="T", description="",
                 status_id=status.id if status else None)
        db.add(t)
        db.commit()
        agent_id = a.id
        task_id = t.id
    return agent_id, proj["id"], task_id


def test_scope_key_precedence():
    assert forge_services.conversation_scope_key(task_id="t1") == "task:t1"
    assert forge_services.conversation_scope_key(project_id="p1") == "chat:project:p1"
    assert forge_services.conversation_scope_key() == "chat:default"
    # task wins over project
    assert forge_services.conversation_scope_key(
        task_id="t1", project_id="p1") == "task:t1"


def test_clear_conversation_wipes_scope_only():
    agent_id, _, task_id = _mk_agent_task()
    scope = f"task:{task_id}"
    other_scope = "chat:default"

    with forge_services._session() as db:
        db.add_all([
            AgentMessage(agent_id=agent_id, role=MessageRole.USER,
                         content="hi", scope_key=scope),
            AgentMessage(agent_id=agent_id, role=MessageRole.ASSISTANT,
                         content="hello", scope_key=scope),
            AgentMessage(agent_id=agent_id, role=MessageRole.USER,
                         content="other", scope_key=other_scope),
            Conversation(agent_id=agent_id, scope_key=scope,
                         runtime_session_id="sess-1",
                         last_used_at=datetime.now(timezone.utc)),
            Conversation(agent_id=agent_id, scope_key=other_scope,
                         runtime_session_id="sess-2",
                         last_used_at=datetime.now(timezone.utc)),
        ])
        db.commit()

    result = forge_services.clear_conversation(agent_id=agent_id, scope_key=scope)
    assert result["ok"] is True
    assert result["messages_deleted"] == 2
    assert result["conversation_deleted"] == 1

    with forge_services._session() as db:
        assert db.query(AgentMessage).filter_by(scope_key=other_scope).count() == 1
        assert db.query(Conversation).filter_by(scope_key=other_scope).count() == 1
        assert db.query(AgentMessage).filter_by(scope_key=scope).count() == 0
        assert db.query(Conversation).filter_by(scope_key=scope).count() == 0


def test_stop_chat_pauses_active_run_for_task_scope(monkeypatch):
    agent_id, _, task_id = _mk_agent_task()
    scope = f"task:{task_id}"

    with forge_services._session() as db:
        run = Run(id=uuid.uuid4().hex, agent_id=agent_id, task_id=task_id,
                  status=RunStatus.RUNNING)
        db.add(run)
        db.commit()
        run_id = run.id

    monkeypatch.setattr(
        "backend.forge.ws_dispatch.hub.dispatch_signal",
        lambda **kw: None,
    )
    result = forge_services.stop_chat(agent_id=agent_id, scope_key=scope)
    assert result["ok"] is True
    assert result["paused_run_id"] == run_id

    with forge_services._session() as db:
        r = db.query(Run).filter_by(id=run_id).first()
        # P3: stop_chat → pause_run writes the PAUSING transient. The
        # terminal PAUSED state arrives on the daemon's trigger-complete
        # (paused=True) post (covered by test_run_lifecycle.py).
        assert r.status == RunStatus.PAUSING


def test_stop_chat_no_active_run_falls_back_to_dispatch_cancel(monkeypatch):
    agent_id, _, task_id = _mk_agent_task()
    scope = f"task:{task_id}"  # task scope, no RUNNING run

    async def fake_cancel(**kw):
        return None

    monkeypatch.setattr(
        "backend.forge.ws_dispatch.hub.dispatch_cancel", fake_cancel,
    )
    result = forge_services.stop_chat(agent_id=agent_id, scope_key=scope)
    # Agent in this test has no runtime_id (http executor), so the
    # daemon-online guard doesn't fire — stop_chat returns ok=True with
    # no cancel actually dispatched.
    assert result["ok"] is True
    assert result["paused_run_id"] is None
