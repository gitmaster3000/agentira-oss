"""Dispatch task_available to connected daemons when a task is assigned to a forge agent.

Called from the REST API task assignment flow.
"""

from __future__ import annotations

import asyncio
import logging

from backend.db import SessionLocal
from backend.forge.models import Agent

logger = logging.getLogger("agentira.forge.triggers")


def fire_task_assigned(task_id: str, assignee_name: str) -> None:
    """Synchronous entry point — looks up the agent, then fires the WS dispatch.

    Safe to call from sync FastAPI endpoints; uses asyncio.run_coroutine_threadsafe
    if an event loop is running, otherwise asyncio.run.
    """
    with SessionLocal() as db:
        agent = db.query(Agent).filter(Agent.name == assignee_name).first()
        if not agent or not agent.runtime_id:
            return

    from backend.forge.ws_dispatch import hub
    coro = hub.dispatch_task(
        runtime_id=agent.runtime_id,
        task_id=task_id,
        agent_id=agent.id,
    )

    try:
        loop = asyncio.get_running_loop()
        asyncio.run_coroutine_threadsafe(coro, loop)
    except RuntimeError:
        asyncio.run(coro)
