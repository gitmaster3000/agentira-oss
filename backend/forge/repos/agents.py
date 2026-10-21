"""Data access for removing an agent. Services compose; repos own the SQL."""
from __future__ import annotations

from backend.forge.models import Conversation, QueuedMessage, WebhookLog


def delete_agent_rows(db, agent) -> None:
    """Drop an agent and the rows that FK to it with no ORM cascade (chat
    threads, queued messages, webhook logs); runs/messages cascade via ORM.
    Caller commits."""
    for model in (Conversation, QueuedMessage, WebhookLog):
        db.query(model).filter(model.agent_id == agent.id).delete(
            synchronize_session=False)
    db.delete(agent)
