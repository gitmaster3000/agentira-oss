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
    """Look up the agent by name, schedule a real Run via the unified rail.

    A Run row is created (visible in the UI), the prompt is assembled from
    the task's title + description + DoD items (real work content, not a
    placeholder), and the project's repo_path / conventions / MCP toolset
    are materialized for the agent. finish_run callback closes the loop:
    the agent declares an outcome which the human sees in the runs list.
    """
    with SessionLocal() as db:
        agent = db.query(Agent).filter(Agent.name == assignee_name).first()
        if not agent:
            return  # human assignee (or unknown), nothing to dispatch
        if not agent.runtime_id:
            logger.info("task %s assigned to agent %s but it has no runtime — "
                        "skipping dispatch", task_id, assignee_name)
            return
        agent_id = agent.id

    try:
        from backend.forge import services
        result = services.schedule_task_run(task_id=task_id, agent_id=agent_id)
        if "error" in result:
            logger.warning("schedule_task_run rejected task %s for agent %s: %s",
                           task_id, assignee_name, result["error"])
    except Exception as exc:
        logger.warning("schedule_task_run for task assignment failed: %s", exc)
