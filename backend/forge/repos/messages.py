"""Data access for AgentMessage reads used by the chat-list views. Services
compose; repos own the SQL (CLAUDE.md).
"""
from __future__ import annotations

import json

from backend.forge.models import AgentMessage, MessageRole


def add_question(db, *, agent_id: str, run_id: str, task_id: str,
                 question: str, options: list[str]) -> None:
    """AP-509: post an agent's needs_input question into its task chat as an
    AskUserQuestion card, the shape the chat UIs already render as clickable
    choices plus a free-text answer. Caller commits."""
    db.add(AgentMessage(
        agent_id=agent_id,
        run_id=run_id,
        scope_key=f"task:{task_id}",
        role=MessageRole.TOOL,
        content=question,
        tool_name="AskUserQuestion",
        tool_input=json.dumps({"questions": [{
            "question": question,
            "options": [{"label": o} for o in options],
        }]}),
    ))
