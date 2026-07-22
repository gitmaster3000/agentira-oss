"""Streamed assistant text must grow ONE message, not one row per delta.

OpenClaw (and other token-streaming runtimes) post many small `type=text`
events for a single reply. If append_trigger_events inserts a new
AgentMessage per event, the chat UI shows each word as its own bubble.
"""

from __future__ import annotations

import uuid

import pytest

import backend.db as db_mod
from backend.forge import services as forge_services
from backend.forge.models import (
    AgentMessage, ForgeRuntime, MessageRole, RuntimeStatus,
)


@pytest.fixture(autouse=True)
def test_db(pg):
    yield db_mod.SessionLocal


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


def test_consecutive_text_deltas_merge_into_one_message(test_db):
    agent_id = _mk_agent(test_db)
    trace_id = uuid.uuid4().hex[:12]
    forge_services._TRACE_SCOPE[trace_id] = "chat:default"

    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None,
        events=[
            {"type": "text", "text": "Hel", "model": "m1"},
            {"type": "text", "text": "lo", "model": "m1"},
            {"type": "text", "text": " world", "model": "m1"},
        ],
    )
    # Separate HTTP batch (daemon flushes every ~0.5s) must still append.
    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None,
        events=[{"type": "text", "text": "!"}],
    )

    with forge_services._session() as db:
        rows = (db.query(AgentMessage)
                  .filter(AgentMessage.trace_id == trace_id,
                          AgentMessage.role == MessageRole.ASSISTANT)
                  .order_by(AgentMessage.created_at, AgentMessage.id)
                  .all())
    assert len(rows) == 1, (
        f"expected 1 bubble, got {len(rows)}: {[r.content for r in rows]}"
    )
    assert rows[0].content == "Hello world!"
    assert rows[0].scope_key == "chat:default"


def test_tool_use_breaks_text_coalesce(test_db):
    """After a tool call, the next assistant text is a new message."""
    agent_id = _mk_agent(test_db)
    trace_id = uuid.uuid4().hex[:12]

    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None,
        events=[
            {"type": "text", "text": "I'll look that up."},
            {"type": "tool_use", "tool": "Read", "input": {"path": "x"}},
            {"type": "tool_result", "tool": "Read", "output": "file body"},
            {"type": "text", "text": "Here"},
            {"type": "text", "text": " it is."},
        ],
    )

    with forge_services._session() as db:
        texts = (db.query(AgentMessage)
                   .filter(AgentMessage.trace_id == trace_id,
                           AgentMessage.role == MessageRole.ASSISTANT)
                   .order_by(AgentMessage.created_at, AgentMessage.id)
                   .all())
        tools = (db.query(AgentMessage)
                   .filter(AgentMessage.trace_id == trace_id,
                           AgentMessage.role == MessageRole.TOOL)
                   .count())
    assert [t.content for t in texts] == ["I'll look that up.", "Here it is."]
    assert tools == 2


def test_replace_flag_overwrites_open_bubble_not_appends(test_db):
    """Runtime rewrites (full snapshot, not a delta) must SET content.

    Without replace, coalescing appends full restarts and the UI shows the
    monologue looping ('Got it…' repeated).
    """
    agent_id = _mk_agent(test_db)
    trace_id = uuid.uuid4().hex[:12]
    forge_services._TRACE_SCOPE[trace_id] = "chat:default"

    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None,
        events=[
            {"type": "text", "text": "Got it — let's fix this."},
            {"type": "text", "text": " Got it — let's fix this. Scanning…"},  # delta-style append
            # Full restart snapshot (no shared prefix growth) — must replace.
            {"type": "text",
             "text": "Got it — let's fix this.\n\nI'll scan the frontend.",
             "replace": True},
        ],
    )

    with forge_services._session() as db:
        rows = (db.query(AgentMessage)
                  .filter(AgentMessage.trace_id == trace_id,
                          AgentMessage.role == MessageRole.ASSISTANT)
                  .all())
    assert len(rows) == 1
    assert rows[0].content == "Got it — let's fix this.\n\nI'll scan the frontend."
    # Must NOT contain the middle fragment twice / looped restarts.
    assert rows[0].content.count("Got it") == 1


def test_openclaw_replace_snapshots_across_tools_collapse_to_one(test_db):
    """OpenClaw stream_events rebroadcasts the *whole-turn* snapshot on every
    chat frame (with replace:true), interleaved with tool calls. Each snapshot
    used to land as a NEW assistant row because a TOOL row breaks the open
    bubble — so one reply got stored N times. A replace:true snapshot is the
    full assistant reply: it must collapse to ONE assistant text row per trace,
    across intervening tool rows.
    """
    agent_id = _mk_agent(test_db)
    trace_id = uuid.uuid4().hex[:12]
    forge_services._TRACE_SCOPE[trace_id] = "task:abc"
    full = ("Let me start.The README is minimal."
            "Good — I'm on branch X.")

    # segment 1 streamed as a plain delta
    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None,
        events=[{"type": "text", "text": "Let me start."}])
    # tool round (separate HTTP batch, as the daemon flushes)
    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None,
        events=[{"type": "tool_use", "tool": "exec",
                 "input": {"command": "ls"}}])
    # whole-turn snapshot re-broadcast — replace:true
    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None,
        events=[{"type": "text",
                 "text": "Let me start.The README is minimal.",
                 "replace": True, "model": "qwen"}])
    # another tool round, then the final whole-turn snapshot
    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None,
        events=[{"type": "tool_use", "tool": "exec",
                 "input": {"command": "git log"}}])
    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None,
        events=[{"type": "text", "text": full,
                 "replace": True, "model": "qwen"}])

    with forge_services._session() as db:
        texts = (db.query(AgentMessage)
                   .filter(AgentMessage.trace_id == trace_id,
                           AgentMessage.role == MessageRole.ASSISTANT)
                   .all())
        tools = (db.query(AgentMessage)
                   .filter(AgentMessage.trace_id == trace_id,
                           AgentMessage.role == MessageRole.TOOL)
                   .count())
    assert len(texts) == 1, (
        f"expected 1 bubble, got {len(texts)}: {[t.content for t in texts]}")
    assert texts[0].content == full
    assert tools == 2


def test_duplicate_tool_rows_deduped(test_db):
    """A resent/redelivered tool step must not create duplicate TOOL rows."""
    agent_id = _mk_agent(test_db)
    trace_id = uuid.uuid4().hex[:12]

    ev = {"type": "tool_use", "tool": "exec", "input": {"command": "ls -la"}}
    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None, events=[ev])
    # same step redelivered in a later batch
    forge_services.append_trigger_events(
        agent_id, trace_id=trace_id, run_id=None, events=[ev])

    with forge_services._session() as db:
        tools = (db.query(AgentMessage)
                   .filter(AgentMessage.trace_id == trace_id,
                           AgentMessage.role == MessageRole.TOOL)
                   .count())
    assert tools == 1
