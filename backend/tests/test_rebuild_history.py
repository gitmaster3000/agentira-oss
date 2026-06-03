"""Context assembly — one token-budgeted path (AP-181).

assemble_context replaces the old two-path _prepend_history_for_prompt
(task→200KB incl tools + latest Run.summary; chat→last-20 no tools):

  - native resume available  → return the prompt unchanged (runtime carries it)
  - otherwise                → rebuild newest→oldest against a TOKEN budget,
    ALWAYS including tool events, for every scope
  - over budget              → older turns are carried by the conversation's
    rolling summary instead of being silently dropped
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
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


# ── native resume short-circuits ─────────────────────────────────────────

def test_native_resume_returns_prompt_unchanged():
    agent_id, task_id = _mk_agent_task()
    scope = f"task:{task_id}"
    with forge_services._session() as db:
        db.add(AgentMessage(agent_id=agent_id, role=MessageRole.USER,
                            content="prior", scope_key=scope))
        db.commit()
    out = forge_services.assemble_context(
        agent_id=agent_id, scope_key=scope, current="go",
        native_resume_available=True,
    )
    assert out == "go", "native resume carries history — no rebuilt preamble"


# ── rebuild includes tool events, for every scope ────────────────────────

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
                         scope_key=scope, tool_name="Bash",
                         tool_input="git status"),
            AgentMessage(agent_id=agent_id, role=MessageRole.TOOL,
                         scope_key=scope, tool_output="working tree clean"),
        ])
        db.commit()
    out = forge_services.assemble_context(
        agent_id=agent_id, scope_key=scope, current="next prompt")
    assert "User: run git status" in out
    assert "Assistant: On it." in out
    assert "Tool: Used Bash(git status)" in out
    assert "Tool: → working tree clean" in out
    assert out.endswith("next prompt")


def test_chat_scope_now_includes_tools_too():
    """The old chat path excluded tool events; the unified path includes them
    for every scope."""
    agent_id, _ = _mk_agent_task()
    scope = "chat:default"
    with forge_services._session() as db:
        db.add_all([
            AgentMessage(agent_id=agent_id, role=MessageRole.USER,
                         content="hello", scope_key=scope),
            AgentMessage(agent_id=agent_id, role=MessageRole.TOOL,
                         scope_key=scope, tool_name="Bash", tool_input="ls"),
        ])
        db.commit()
    out = forge_services.assemble_context(
        agent_id=agent_id, scope_key=scope, current="x")
    assert "Tool: Used Bash(ls)" in out


# ── token budget (replaces 200KB byte-cap / 20-msg cap) ──────────────────

def test_token_budget_drops_oldest_keeps_recent():
    agent_id, task_id = _mk_agent_task()
    scope = f"task:{task_id}"
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    big = "x" * 400  # ~100 tokens per line
    with forge_services._session() as db:
        for i in range(30):
            db.add(AgentMessage(
                agent_id=agent_id,
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                content=f"m{i}:{big}", scope_key=scope,
                created_at=base + timedelta(minutes=i),
            ))
        db.commit()
    out = forge_services.assemble_context(
        agent_id=agent_id, scope_key=scope, current="now", token_budget=300)
    assert "m29:" in out, "most-recent turn kept"
    assert "m0:" not in out, "oldest turn dropped by the token budget"


# ── over-budget → rolling-summary compaction (no silent drop) ────────────

def test_over_budget_carries_rolling_summary():
    agent_id, task_id = _mk_agent_task()
    scope = f"task:{task_id}"
    forge_services.upsert_conversation(
        agent_id=agent_id, scope_key=scope,
        rolling_summary="Set up auth and the DB schema earlier.")
    big = "y" * 400
    with forge_services._session() as db:
        for i in range(20):
            db.add(AgentMessage(agent_id=agent_id, role=MessageRole.USER,
                                content=f"q{i}:{big}", scope_key=scope))
        db.commit()
    out = forge_services.assemble_context(
        agent_id=agent_id, scope_key=scope, current="cont", token_budget=300)
    assert "Earlier context (summary): Set up auth and the DB schema earlier." in out
    assert out.endswith("cont")


def test_run_summary_used_when_no_rolling_summary():
    agent_id, task_id = _mk_agent_task()
    _mk_run(agent_id, task_id, summary="Old attempt — rabbit hole.")
    _mk_run(agent_id, task_id, summary="Fixed login redirect bug.")
    scope = f"task:{task_id}"
    with forge_services._session() as db:
        db.add(AgentMessage(agent_id=agent_id, role=MessageRole.USER,
                            content="hi", scope_key=scope))
        db.commit()
    out = forge_services.assemble_context(
        agent_id=agent_id, scope_key=scope, current="resume please")
    assert "Earlier context (summary): Fixed login redirect bug." in out
    assert "Old attempt" not in out
    assert out.index("Earlier context") < out.index("</conversation history>")
