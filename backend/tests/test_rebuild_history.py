"""AP-106 (post-AP-93): history rebuild fidelity when native resume is
unavailable. Applies to task-scoped chats — the scope shape AP-93
introduced — and to any runtime that lacks --resume (OpenClaw, future
gateways). When rebuilt, the preamble must include TOOL events and the
most-recent Run.summary for the task, capped by total byte size. Chat
scopes retain the original 20-entry cap and exclude tool events.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    Agent, AgentMessage, MessageRole, Run, RunStatus,
)


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
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


def _mk_agent_task():
    bot = core_services.create_service_account("bot1")
    proj = core_services.create_project("P")
    from backend.models import Task, Status
    with forge_services._session() as db:
        a = Agent(id=bot["id"], profile_id=bot["id"], name="bot1",
                  executor_type="http", model="")
        db.add(a)
        status = db.query(Status).first()
        t = Task(id=uuid.uuid4().hex, project_id=proj["id"],
                 key="P-1", title="T", description="",
                 status_id=status.id if status else None)
        db.add(t)
        db.commit()
        return a.id, t.id


def _mk_run(agent_id: str, task_id: str, summary: str | None = None) -> str:
    run_id = uuid.uuid4().hex[:12]
    with forge_services._session() as db:
        db.add(Run(id=run_id, agent_id=agent_id, task_id=task_id,
                   status=RunStatus.COMPLETED, summary=summary))
        db.commit()
    return run_id


def test_rebuild_includes_tool_messages():
    agent_id, task_id = _mk_agent_task()
    scope = f"task:{task_id}"

    with forge_services._session() as db:
        db.add_all([
            AgentMessage(agent_id=agent_id, role=MessageRole.USER,
                         content="run git status", scope_key=scope),
            AgentMessage(agent_id=agent_id, role=MessageRole.ASSISTANT,
                         content="On it.", scope_key=scope),
            AgentMessage(agent_id=agent_id, role=MessageRole.TOOL,
                         scope_key=scope,
                         tool_name="Bash", tool_input="git status"),
            AgentMessage(agent_id=agent_id, role=MessageRole.TOOL,
                         scope_key=scope,
                         tool_output="working tree clean"),
        ])
        db.commit()

    out = forge_services._prepend_history_for_prompt(
        agent_id=agent_id, scope_key=scope, current="next prompt",
    )
    assert "User: run git status" in out
    assert "Assistant: On it." in out
    assert "Tool: Used Bash(git status)" in out
    assert "Tool: → working tree clean" in out
    assert out.endswith("next prompt")


def test_rebuild_includes_latest_run_summary_when_scope_is_task():
    agent_id, task_id = _mk_agent_task()
    # Two runs on the same task; only the latest summary should appear.
    _mk_run(agent_id, task_id, summary="Old attempt — went down a rabbit hole.")
    _mk_run(agent_id, task_id, summary="Fixed login redirect bug.")
    scope = f"task:{task_id}"

    with forge_services._session() as db:
        db.add(AgentMessage(agent_id=agent_id, role=MessageRole.USER,
                            content="hi", scope_key=scope))
        db.commit()

    out = forge_services._prepend_history_for_prompt(
        agent_id=agent_id, scope_key=scope, current="resume please",
    )
    assert "Run summary: Fixed login redirect bug." in out
    assert "Old attempt" not in out
    summary_idx = out.index("Run summary:")
    close_idx = out.index("</conversation history>")
    assert summary_idx < close_idx


def test_rebuild_respects_byte_cap_for_task_scope():
    agent_id, task_id = _mk_agent_task()
    scope = f"task:{task_id}"

    big = "x" * 5000
    with forge_services._session() as db:
        for i in range(50):
            db.add(AgentMessage(
                agent_id=agent_id,
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                content=f"{i}:{big}", scope_key=scope,
            ))
        db.commit()

    out = forge_services._prepend_history_for_prompt(
        agent_id=agent_id, scope_key=scope, current="now",
    )
    preamble = out[: out.index("now")]
    # ~250KB of message content, capped at the ~200KB preamble budget:
    # bounded (not all 250KB) but still substantial.
    assert 100 * 1024 < len(preamble) < 210 * 1024, len(preamble)
    assert "<conversation history>" in preamble


def test_rebuild_chat_scope_uses_smaller_cap():
    agent_id, _ = _mk_agent_task()
    scope = "chat:default"

    # Explicit strictly-increasing created_at — _utcnow() can return the
    # same value for rows inserted in a tight loop, making the 20-entry
    # cap boundary non-deterministic. Pin the timestamps.
    from datetime import datetime, timedelta, timezone
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with forge_services._session() as db:
        for i in range(50):
            db.add(AgentMessage(
                agent_id=agent_id,
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                content=f"msg-{i}", scope_key=scope,
                created_at=base + timedelta(minutes=i),
            ))
        db.add(AgentMessage(agent_id=agent_id, role=MessageRole.TOOL,
                            scope_key=scope,
                            tool_name="Bash", tool_input="ls",
                            created_at=base + timedelta(minutes=50)))
        db.commit()

    out = forge_services._prepend_history_for_prompt(
        agent_id=agent_id, scope_key=scope, current="next",
    )
    assert "msg-49" in out
    assert "msg-30" in out
    assert "msg-29" not in out
    assert "msg-0" not in out
    assert "Tool: Used Bash" not in out
