"""list_all_conversations: the global /chat list aggregating every agent's chats.

Backs GET /forge/chats — one row per (agent, scope_key), newest first, with
agent name and a last-message preview so the frontend can render the chat
picker without one call per agent.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta

import pytest

from backend.forge import services as fs
from backend.forge.models import Agent, AgentMessage, MessageRole


@pytest.fixture(autouse=True)
def org(pg):
    """Shared ephemeral-Postgres harness with org context pinned."""
    return pg


def _agent(name: str) -> str:
    # Insert the Agent row directly — list_all_conversations only needs the
    # agent + its messages, no runtime. org_id is auto-stamped by before_flush
    # from the pinned org context.
    with fs._session() as db:
        a = Agent(name=name, executor_type="cli")
        db.add(a)
        db.commit()
        return a.id


def _msg(agent_id: str, scope: str, content: str, minute: int):
    with fs._session() as db:
        db.add(AgentMessage(
            agent_id=agent_id, scope_key=scope, role=MessageRole.USER,
            content=content,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minute),
        ))
        db.commit()


def test_aggregates_across_agents_newest_first():
    a = _agent("Alpha")
    b = _agent("Beta")
    _msg(a, "chat:default", "hi from a", 1)
    _msg(b, "chat:default", "hi from b", 5)  # newest

    chats = fs.list_all_conversations()
    assert len(chats) == 2
    # Newest conversation first.
    assert chats[0]["agent_id"] == b
    assert chats[0]["agent_name"] == "Beta"
    assert chats[0]["last_message"] == "hi from b"
    assert chats[1]["agent_id"] == a


def test_separate_row_per_scope_with_counts():
    a = _agent("Alpha")
    _msg(a, "chat:default", "one", 1)
    _msg(a, "task:T1", "two", 2)
    _msg(a, "task:T1", "three", 3)

    chats = fs.list_all_conversations()
    by_scope = {c["scope_key"]: c for c in chats}
    assert by_scope["chat:default"]["message_count"] == 1
    assert by_scope["task:T1"]["message_count"] == 2
    assert by_scope["task:T1"]["last_message"] == "three"
