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
    """AP-129: assigning an agent to a task creates a READY run, NOT a
    running one. The user lands on the Run page, sees the prepared
    prompt, edits it if needed, and clicks Start.

    Why: the previous behavior (schedule_task_run → straight to RUNNING)
    surprised users — assigning an agent burned LLM tokens before the
    user had a chance to look at what was about to be sent. The READY
    gate puts the user back in control on the manual-assignment path.

    The Conductor's autopilot tick (which DOES auto-dispatch) bypasses
    this trigger and calls schedule_task_run directly — that opt-in
    behavior is unaffected.
    """
    with SessionLocal() as db:
        agent = db.query(Agent).filter(Agent.name == assignee_name).first()
        if not agent:
            return  # human assignee (or unknown), nothing to dispatch
        if not agent.runtime_id:
            logger.info("task %s assigned to agent %s but it has no runtime — "
                        "skipping prepare", task_id, assignee_name)
            return
        agent_id = agent.id

    try:
        from backend.forge import services
        result = services.prepare_task_run(task_id=task_id, agent_id=agent_id)
        if "error" in result:
            logger.warning("prepare_task_run rejected task %s for agent %s: %s",
                           task_id, assignee_name, result["error"])
    except Exception as exc:
        logger.warning("prepare_task_run for task assignment failed: %s", exc)
