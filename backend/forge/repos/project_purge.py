"""Forge-side cascade for a project being deleted.

Runs and chats are forge-owned but carry no ORM cascade back to Project/Task,
so a core `db.delete(project)` would FK-violate on `forge_runs`. The core
delete (services.delete_project) calls this first to drop the forge rows and
clear the agent default-project pointer that would otherwise block the delete.
"""
from __future__ import annotations

from sqlalchemy import or_

from backend.forge.models import (Run, Conversation, AgentMessage,
                                  QueuedMessage, Agent)


def purge_project_data(db, *, project_id: str, task_ids: list[str]) -> None:
    # Runs tied to the project directly or to any of its tasks. Capture ids
    # so we also drop legacy `run:<id>` chat rows keyed off them.
    run_filter = [Run.project_id == project_id]
    if task_ids:
        run_filter.append(Run.task_id.in_(task_ids))
    runs = db.query(Run).filter(or_(*run_filter)).all()
    run_scopes = [f"run:{r.id}" for r in runs]
    for r in runs:
        db.delete(r)

    # Chat rows are keyed by a string scope_key (no FK): the project chat,
    # each task chat, and any legacy per-run scope.
    scopes = [f"chat:project:{project_id}"] + \
             [f"task:{t}" for t in task_ids] + run_scopes
    for model in (Conversation, AgentMessage, QueuedMessage):
        db.query(model).filter(model.scope_key.in_(scopes)).delete(
            synchronize_session=False)

    # Agents that defaulted to this project lose the pointer (FK would block).
    db.query(Agent).filter(Agent.default_project_id == project_id).update(
        {Agent.default_project_id: None}, synchronize_session=False)
