"""Bridge from REST task-assignment flow to the trigger rail.

When a task is assigned to a forge agent, fire a trigger so the daemon picks
up the work. The prompt is a placeholder for now; the template/gate engine
(planned) will produce a real prompt from the task description + ACs.
"""

from __future__ import annotations

import logging

from backend.db import SessionLocal
from backend.forge.models import Agent

logger = logging.getLogger("agentira.forge.triggers")


def fire_task_assigned(task_id: str, assignee_name: str) -> None:
    """Look up the agent by name, then dispatch a trigger via the unified rail."""
    with SessionLocal() as db:
        agent = db.query(Agent).filter(Agent.name == assignee_name).first()
        if not agent or not agent.runtime_id:
            return
        agent_id = agent.id

    # TODO: build the real prompt from task description, ACs, and template config.
    placeholder = f"Task {task_id} assigned to you. Begin work."
    try:
        from backend.forge import services
        services.dispatch_trigger(agent_id, placeholder, kind="run_step")
    except Exception as exc:
        logger.warning("dispatch_trigger for task assignment failed: %s", exc)
