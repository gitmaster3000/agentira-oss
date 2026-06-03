"""Per-conversation message queue (AP-179).

A conversation is single-threaded — at most one live turn at a time. A message
typed while a turn is running is *queued* here, not steered into the running
turn, and dispatches FIFO when the active turn reaches a terminal state. Keyed
by (agent_id, scope_key) = the conversation, so a queued message survives even
if the in-flight run is discarded.

Stateless module of functions over the forge_queued_messages table. Replaces
the old Run.pending_steer interrupt-and-fold mechanism.
"""

from __future__ import annotations

import json

from backend.db import SessionLocal
from backend.forge.models import QueuedMessage


def enqueue(*, agent_id: str, scope_key: str, content: str,
            user_context: dict | None = None) -> str:
    """Append a message to the conversation's queue. Returns the queued id."""
    with SessionLocal() as db:
        qm = QueuedMessage(
            agent_id=agent_id,
            scope_key=scope_key,
            content=content,
            user_context_json=json.dumps(user_context) if user_context else None,
        )
        db.add(qm)
        db.commit()
        db.refresh(qm)
        return qm.id


def dequeue_oldest(*, agent_id: str, scope_key: str) -> dict | None:
    """Pop the oldest queued message for this conversation (FIFO), or None.

    Deletes the row and returns {content, user_context}. The caller dispatches
    it as the next turn.
    """
    with SessionLocal() as db:
        qm = (db.query(QueuedMessage)
                .filter(QueuedMessage.agent_id == agent_id,
                        QueuedMessage.scope_key == scope_key)
                .order_by(QueuedMessage.created_at.asc())
                .first())
        if not qm:
            return None
        out = {
            "content": qm.content,
            "user_context": (json.loads(qm.user_context_json)
                             if qm.user_context_json else None),
        }
        db.delete(qm)
        db.commit()
        return out


def list_for_scope(*, agent_id: str, scope_key: str) -> list[dict]:
    """Queued messages for this conversation, oldest first — for the UI's
    "queued" pills under the active turn."""
    with SessionLocal() as db:
        rows = (db.query(QueuedMessage)
                  .filter(QueuedMessage.agent_id == agent_id,
                          QueuedMessage.scope_key == scope_key)
                  .order_by(QueuedMessage.created_at.asc())
                  .all())
        return [{"id": r.id, "content": r.content,
                 "created_at": r.created_at.isoformat() if r.created_at else None}
                for r in rows]
