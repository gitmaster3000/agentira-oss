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

import pytest

from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    Agent, AgentMessage, MessageRole, Run, RunStatus,
)


@pytest.fixture(autouse=True)
def _harness(pg):
    """Shared ephemeral-Postgres harness (org context pinned by `pg`)."""
    yield


def _mk_agent_task():
    bot = core_services.create_service_account("bot1")
    proj = core_services.create_project("P")
    from backend.models import Task, Status
    with forge_services._session() as db:
        a = Agent(id=bot["id"], profile_id=bot["id"], name="bot1",
                  executor_type="http", model="")
        db.add(a)
        status = db.query(Status).first()
        t = Task(id=uuid.uuid4().hex[:12], project_id=proj["id"],
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


# ── row cap bounds the fetch (prod OOM 2026-07-07) ───────────────────────

def test_row_cap_bounds_history_fetch(monkeypatch):
    """A giant history must not be materialized wholesale: only the newest
    _CONTEXT_ROW_CAP rows are fetched (the token budget then trims further)."""
    from backend.forge import context as ctx
    monkeypatch.setattr(ctx, "_CONTEXT_ROW_CAP", 5)
    agent_id, task_id = _mk_agent_task()
    scope = f"task:{task_id}"
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with forge_services._session() as db:
        for i in range(12):
            db.add(AgentMessage(
                agent_id=agent_id, role=MessageRole.USER,
                content=f"r{i}:hello", scope_key=scope,
                created_at=base + timedelta(minutes=i),
            ))
        db.commit()
    out = forge_services.assemble_context(
        agent_id=agent_id, scope_key=scope, current="now",
        token_budget=100_000)
    assert "r11:" in out, "newest row kept"
    assert "r7:" in out, "cap window (newest 5) kept"
    assert "r6:" not in out, "rows beyond the cap not fetched"


# ── field fetch caps bound per-row memory (prod OOM #3, 2026-07-07) ──────

def test_giant_rows_fetched_truncated():
    """Megabyte USER rows (Conductor board dumps) and tool blobs must be
    truncated SQL-side: the assembled context carries at most
    _CONTENT_FETCH_CAP chars of content and ~_TOOL_ENTRY_TRUNCATE of a tool
    entry, never the full stored blob."""
    from backend.forge import context as ctx
    agent_id, task_id = _mk_agent_task()
    scope = f"task:{task_id}"
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    giant_user = "U" * (ctx._CONTENT_FETCH_CAP + 50_000)
    giant_tool = "T" * (ctx._TOOL_ENTRY_TRUNCATE * 3)
    with forge_services._session() as db:
        db.add(AgentMessage(
            agent_id=agent_id, role=MessageRole.USER,
            content=giant_user, scope_key=scope, created_at=base))
        db.add(AgentMessage(
            agent_id=agent_id, role=MessageRole.TOOL,
            content="tool", tool_output=giant_tool, tool_name=None,
            scope_key=scope,
            created_at=base + timedelta(minutes=1)))
        db.commit()
    out = forge_services.assemble_context(
        agent_id=agent_id, scope_key=scope, current="now",
        token_budget=1_000_000)
    # Tool entry: renderer keeps _TOOL_ENTRY_TRUNCATE chars + ellipsis; the
    # SQL fetch cap must still let the renderer detect the overflow.
    assert ("T" * ctx._TOOL_ENTRY_TRUNCATE) + "…" in out
    assert "T" * (ctx._TOOL_ENTRY_TRUNCATE + 2) not in out
    # USER content: capped at the SQL fetch limit, not the stored size.
    assert "U" * ctx._CONTENT_FETCH_CAP in out
    assert "U" * (ctx._CONTENT_FETCH_CAP + 1) not in out


# ── a broken history rebuild degrades to a fresh dispatch, never a crash ──
# (2026-07-22 hardening, DiskFull recurrence at 23:39 — a wedged/erroring
# history query must not kill the whole turn.)

def test_broken_history_query_degrades_to_current(monkeypatch):
    """If the history rebuild query raises (OperationalError or anything
    else), assemble_context must log a warning and return `current`
    unchanged — never propagate the exception into the caller."""
    from backend.forge import context as ctx
    agent_id, task_id = _mk_agent_task()
    scope = f"task:{task_id}"
    with forge_services._session() as db:
        db.add(AgentMessage(agent_id=agent_id, role=MessageRole.USER,
                            content="prior", scope_key=scope))
        db.commit()

    class _BoomSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query(self, *a, **kw):
            raise RuntimeError("boom — session wedged")

    monkeypatch.setattr(forge_services, "_session", lambda: _BoomSession())
    out = ctx.assemble_context(
        agent_id=agent_id, scope_key=scope, current="fresh dispatch")
    assert out == "fresh dispatch"


def test_broken_history_query_operational_error_degrades_to_current(monkeypatch):
    from sqlalchemy.exc import OperationalError
    from backend.forge import context as ctx
    agent_id, task_id = _mk_agent_task()
    scope = f"task:{task_id}"

    class _BoomSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query(self, *a, **kw):
            raise OperationalError("SELECT 1", {}, Exception("connection lost"))

    monkeypatch.setattr(forge_services, "_session", lambda: _BoomSession())
    out = ctx.assemble_context(
        agent_id=agent_id, scope_key=scope, current="fresh dispatch 2")
    assert out == "fresh dispatch 2"
