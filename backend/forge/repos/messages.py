"""Data access for AgentMessage reads used by the chat-list views. Services
compose; repos own the SQL (CLAUDE.md).
"""
from __future__ import annotations

from sqlalchemy import func

from backend.forge.models import AgentMessage


def last_message_per_thread(db) -> dict[tuple[str, str], str]:
    """{(agent_id, scope_key): content} for the newest non-empty message in
    every thread — one row_number() window query instead of one query per
    thread (the N+1 behind the slow /forge/chats load)."""
    ranked = (
        db.query(
            AgentMessage.agent_id,
            AgentMessage.scope_key,
            AgentMessage.content,
            func.row_number().over(
                partition_by=(AgentMessage.agent_id, AgentMessage.scope_key),
                order_by=AgentMessage.created_at.desc(),
            ).label("rn"),
        )
        .filter(AgentMessage.scope_key.isnot(None), AgentMessage.content != "")
        .subquery()
    )
    rows = (db.query(ranked.c.agent_id, ranked.c.scope_key, ranked.c.content)
              .filter(ranked.c.rn == 1)
              .all())
    return {(aid, sk): content for aid, sk, content in rows}
