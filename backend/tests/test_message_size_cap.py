"""AP-421: prod OOM #3 — Conductor planning prompts + streamed tool events
were landing multi-megabyte AgentMessage rows (up to 2.9MB each; 884MB
across the newest 1000 rows of chat:default alone). The write side must
cap every text field at ingestion, regardless of which code path
constructs the row (dispatch_trigger, append_trigger_events, the legacy
send_runtime_message gateway path, ...).
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

import pytest

import backend.db as db_mod
from backend.forge import services as forge_services
from backend.forge.models import (
    AgentMessage, ForgeRuntime, RuntimeStatus, MESSAGE_FIELD_CAP,
)


@pytest.fixture(autouse=True)
def test_db(pg):
    """Shared ephemeral-Postgres harness; org context is already pinned. The
    bodies use the yielded value as a sessionmaker, so yield the real one."""
    yield db_mod.SessionLocal


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


def _mk_agent(TestSession) -> str:
    db = TestSession()
    rt = ForgeRuntime(daemon_id="d1", provider="claude",
                      binary_path="/tmp/claude", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    return agent["id"]


# ── model-level cap (single choke point for every AgentMessage insert) ──

def test_model_caps_oversized_content_at_the_orm_level():
    huge = "x" * (MESSAGE_FIELD_CAP * 3)
    m = AgentMessage(agent_id="a", role=forge_services.MessageRole.USER,
                     content=huge, tool_input=huge, tool_output=huge)
    assert len(m.content.encode("utf-8")) <= MESSAGE_FIELD_CAP + 200
    assert "truncated" in m.content
    assert len(m.tool_input.encode("utf-8")) <= MESSAGE_FIELD_CAP + 200
    assert len(m.tool_output.encode("utf-8")) <= MESSAGE_FIELD_CAP + 200


def test_model_leaves_small_content_untouched():
    m = AgentMessage(agent_id="a", role=forge_services.MessageRole.USER,
                     content="hello")
    assert m.content == "hello"


# ── dispatch_trigger — the planning-turn / chat ingestion path ──────────

def test_planning_turn_stores_no_user_row_above_the_cap(test_db):
    """A pathologically large planning prompt (e.g. thousands of unassigned
    tasks) must still land a capped row, not a megabyte one."""
    agent_id = _mk_agent(test_db)
    huge_prompt = "QUEUE PLANNING.\n" + ("task row\n" * 500_000)  # ~4.5MB
    assert len(huge_prompt.encode("utf-8")) > MESSAGE_FIELD_CAP

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        _drive(lambda: forge_services.dispatch_trigger(
            agent_id, huge_prompt, kind="chat", scope_key="chat:default"))

    with forge_services._session() as db:
        rows = (db.query(AgentMessage)
                  .filter(AgentMessage.agent_id == agent_id,
                          AgentMessage.role == forge_services.MessageRole.USER)
                  .all())
    assert len(rows) == 1
    stored = rows[0].content
    assert len(stored.encode("utf-8")) <= MESSAGE_FIELD_CAP + 200
    assert "truncated" in stored


# ── append_trigger_events — the streamed tool_output ingestion path ─────

def test_append_trigger_events_truncates_oversized_tool_output(test_db):
    agent_id = _mk_agent(test_db)
    trace_id = uuid.uuid4().hex[:12]
    huge_output = "y" * (MESSAGE_FIELD_CAP * 2)

    result = forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None,
        events=[{"type": "tool_result", "tool": "Bash", "output": huge_output}],
    )
    assert result["ok"] is True

    with forge_services._session() as db:
        rows = (db.query(AgentMessage)
                  .filter(AgentMessage.trace_id == trace_id)
                  .all())
    assert len(rows) == 1
    assert len(rows[0].tool_output.encode("utf-8")) <= MESSAGE_FIELD_CAP + 200
    assert "truncated" in rows[0].tool_output


def test_append_trigger_events_leaves_normal_output_untouched(test_db):
    agent_id = _mk_agent(test_db)
    trace_id = uuid.uuid4().hex[:12]

    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None,
        events=[{"type": "tool_result", "tool": "Bash", "output": "ok"}],
    )
    with forge_services._session() as db:
        row = (db.query(AgentMessage)
                 .filter(AgentMessage.trace_id == trace_id).first())
    assert row.tool_output == "ok"


# ── performance check — realistic bad data stays bounded ────────────────

def test_ingestion_and_context_assembly_stay_bounded_with_large_rows(test_db):
    """Simulate the prod incident: a scope repeatedly fed megabyte-scale
    events (the pre-fix behavior). Ingestion must cap every row at write
    time, so the scope's total on-disk size — and the time to assemble
    context over it — stay bounded instead of growing without limit."""
    import time
    from backend.forge.context import assemble_context

    agent_id = _mk_agent(test_db)
    scope = "chat:default"
    trace_id = uuid.uuid4().hex[:12]

    n_events = 100
    events = [{"type": "tool_result", "tool": "Bash",
              "output": f"row{i}:" + ("z" * (2 * MESSAGE_FIELD_CAP))}
             for i in range(n_events)]

    t0 = time.monotonic()
    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None, events=events)
    ingest_elapsed = time.monotonic() - t0

    with forge_services._session() as db:
        rows = (db.query(AgentMessage)
                  .filter(AgentMessage.agent_id == agent_id).all())
        total_bytes = sum(len((r.tool_output or "").encode("utf-8"))
                          for r in rows)

    # Without the cap this would be ~100 * 4MB = 400MB; capped, it's bounded
    # by row-count * per-field cap with headroom for the truncation marker.
    assert len(rows) == n_events
    assert total_bytes <= n_events * (MESSAGE_FIELD_CAP + 200)
    assert ingest_elapsed < 5.0, f"ingestion took {ingest_elapsed:.2f}s — unbounded?"

    t0 = time.monotonic()
    out = assemble_context(agent_id=agent_id, scope_key=scope,
                           current="now", token_budget=50_000)
    assemble_elapsed = time.monotonic() - t0
    assert assemble_elapsed < 5.0, f"assembly took {assemble_elapsed:.2f}s — unbounded?"
    assert isinstance(out, str)
