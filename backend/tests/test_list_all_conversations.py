"""list_all_conversations: the global /chat list aggregating every agent's chats.

Backs GET /forge/chats — one row per (agent, scope_key), newest first, with
agent name and a last-message preview so the frontend can render the chat
picker without one call per agent.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta

import pytest

from sqlalchemy import text

from backend.forge import services as fs
from backend.forge.models import Agent, AgentMessage, MessageRole
from backend.models import Profile


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


# ── AP-309: a blank Agent.name rendered a red "?" / "Agent" row in the
# global chat list for every failed-execution thread. agent_name must never
# come back empty — fall back to the linked profile, then a neutral label.

def test_blank_name_falls_back_to_profile_name():
    with fs._session() as db:
        prof = Profile(name="Gamma", account_type="agentira_agent")
        db.add(prof)
        db.flush()
        a = Agent(name="", profile_id=prof.id, executor_type="cli")
        db.add(a)
        db.commit()
        aid = a.id
    _msg(aid, "chat:default", "boom", 1)

    chats = fs.list_all_conversations()
    assert chats[0]["agent_id"] == aid
    assert chats[0]["agent_name"] == "Gamma"


def test_orphaned_thread_is_excluded():
    """The real AP-309 cause: forge_messages.agent_id points at an agent that
    was deleted / merged away (the live schema has no enforced FK on that
    column). Those dead threads — all old "⚠ Agent execution failed: …" runs —
    rendered as red "?" rows. You can't chat with a deleted agent, so the
    global list must drop them, not relabel them."""
    keep = _agent("Keeper")
    ghost = _agent("Ghost")
    _msg(keep, "chat:default", "still here", 1)
    _msg(ghost, "chat:default", "⚠ Agent execution failed: Not logged in", 2)

    # Simulate prod drift: remove the agent row out from under its messages.
    # session_replication_role=replica suspends FK enforcement so the orphan
    # state the production DB actually contains can be reproduced here.
    with fs._session() as db:
        db.execute(text("SET session_replication_role = replica"))
        db.execute(text("DELETE FROM forge_agents WHERE id = :id"), {"id": ghost})
        db.execute(text("SET session_replication_role = origin"))
        db.commit()

    chats = fs.list_all_conversations()
    ids = [c["agent_id"] for c in chats]
    assert keep in ids
    assert ghost not in ids          # orphaned thread dropped, not shown as "?"
