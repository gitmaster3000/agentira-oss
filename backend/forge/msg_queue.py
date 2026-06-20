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
import logging

from backend.db import SessionLocal
from backend.forge.models import QueuedMessage, Run

logger = logging.getLogger("agentira.forge.msg_queue")


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


def flush_next(agent_id: str, *, scope_key: str = "",
               run_id: str | None = None) -> bool:
    """Dispatch the oldest queued message for a conversation whose turn just
    reached a terminal state (completed / failed / cancelled). FIFO, one per
    call — the dispatched turn's own completion flushes the next. Queued
    messages exist only for task scopes, so when scope_key isn't given we
    derive it from the run's task. Best-effort; never raises. Returns True if a
    message was dispatched."""
    try:
        scope = scope_key
        if not scope and run_id:
            with SessionLocal() as db:
                r = db.query(Run).filter(Run.id == run_id).first()
                if r and r.task_id:
                    scope = f"task:{r.task_id}"
        if not scope:
            return False
        nxt = dequeue_oldest(agent_id=agent_id, scope_key=scope)
        if not nxt:
            return False
        # Lazy import avoids a cycle with services (which calls us back).
        from backend.forge.services import send_runtime_message
        send_runtime_message(agent_id, content=nxt["content"], scope_key=scope,
                             user_context=nxt.get("user_context"))
        return True
    except Exception as exc:  # noqa: BLE001 — never fail completion on the queue
        logger.warning("queued-message flush failed: %s", exc)
        return False


def remove(*, queued_id: str, agent_id: str, scope_key: str) -> bool:
    """Cancel a single queued message before it dispatches. Scoped to its
    (agent, scope) so a stale id from another conversation can't delete it.
    Returns True if a row was removed."""
    with SessionLocal() as db:
        qm = (db.query(QueuedMessage)
                .filter(QueuedMessage.id == queued_id,
                        QueuedMessage.agent_id == agent_id,
                        QueuedMessage.scope_key == scope_key)
                .first())
        if not qm:
            return False
        db.delete(qm)
        db.commit()
        return True


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
