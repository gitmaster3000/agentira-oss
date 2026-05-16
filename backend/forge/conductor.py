"""AP-80 Conductor — auto-dispatch todo tasks to idle conductor-enabled agents.

The Conductor is a ~60s tick on top of APScheduler. Each tick:

  1. List Profile rows with `conductor_enabled = True` AND `default_project_id`.
  2. For each, check if the agent has < `max_concurrent_runs` in-flight runs.
  3. If idle, pick the next eligible todo task in the agent's project
     (assigned to this agent OR unassigned). FIFO by created_at.
  4. Dispatch via the existing `services.schedule_task_run()` pipeline.

Opt-in per agent (default off). FIFO; no smart priority yet. The picker is
exposed as `pick_next_unblocked(project_id, agent_id)` (AP-14) and the
tick itself is `run_tick()` (AP-15).
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from backend.db import SessionLocal
from backend.models import Profile, Task, Status
from backend.forge.models import Agent, Run, RunStatus

logger = logging.getLogger("agentira.forge.conductor")

# AP-15: tick cadence (seconds). Low enough to feel snappy, high enough
# to avoid hammering the DB.
TICK_INTERVAL_S = 60


def _todo_status_id(db) -> str | None:
    """Resolve the id of the `todo` Status row (one query, cached per tick)."""
    row = db.query(Status).filter(Status.name == "todo").first()
    return row.id if row else None


def pick_next_unblocked(*, project_id: str, agent_id: str, db=None) -> "Task | None":
    """AP-14: return the next todo task in `project_id` for `agent_id`, or None.

    Eligible: status == 'todo' AND (assignee == agent_name OR assignee == "").
    Ordered FIFO by created_at. Caller commits/closes the session.
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        todo_id = _todo_status_id(db)
        if not todo_id:
            return None
        agent = db.get(Agent, agent_id)
        if not agent:
            return None
        # Assignee is stored as the agent's name string (legacy).
        q = (db.query(Task)
               .filter(Task.project_id == project_id,
                       Task.status_id == todo_id)
               .filter((Task.assignee == agent.name) | (Task.assignee == "")
                       | (Task.assignee.is_(None)))
               .order_by(Task.created_at.asc()))
        return q.first()
    finally:
        if own_session:
            db.close()


def _agent_in_flight_count(db, agent_id: str) -> int:
    """Live + pending runs for this agent. Anything not in a terminal state."""
    return (db.query(Run)
              .filter(Run.agent_id == agent_id,
                      Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING,
                                      RunStatus.PAUSED]))
              .count())


def run_tick() -> dict:
    """One Conductor pass. Returns a summary of what happened this tick.

    Safe to call repeatedly; idempotent in the sense that already-running
    agents are skipped. Errors per-agent are swallowed and logged — one
    bad row must not stall the rest of the fleet.
    """
    dispatched: list[dict] = []
    skipped: list[dict] = []

    with SessionLocal() as db:
        # Fetch profiles with the conductor flag on. Join to Agent via
        # profile_id so we have the agent row to dispatch with.
        profiles = (db.query(Profile)
                      .filter(Profile.conductor_enabled == True)  # noqa: E712
                      .filter(Profile.default_project_id.isnot(None))
                      .all())
        for prof in profiles:
            agent = (db.query(Agent)
                       .filter(Agent.profile_id == prof.id)
                       .first())
            if not agent:
                skipped.append({"profile": prof.id, "reason": "no_agent"})
                continue
            if not agent.runtime_id:
                skipped.append({"agent": agent.id, "reason": "no_runtime"})
                continue
            cap = max(1, int(prof.max_concurrent_runs or 1))
            inflight = _agent_in_flight_count(db, agent.id)
            if inflight >= cap:
                skipped.append({"agent": agent.id, "reason": "at_capacity",
                                "inflight": inflight, "cap": cap})
                continue
            task = pick_next_unblocked(
                project_id=prof.default_project_id, agent_id=agent.id, db=db,
            )
            if not task:
                skipped.append({"agent": agent.id, "reason": "no_eligible_task"})
                continue
            try:
                from backend.forge import services
                result = services.schedule_task_run(task_id=task.id, agent_id=agent.id)
                if isinstance(result, dict) and result.get("error"):
                    logger.warning("Conductor dispatch error agent=%s task=%s: %s",
                                   agent.id, task.id, result["error"])
                    skipped.append({"agent": agent.id, "task": task.id,
                                    "reason": "dispatch_error", "error": result["error"]})
                else:
                    dispatched.append({"agent": agent.id, "task": task.id,
                                       "run_id": result.get("run_id") if isinstance(result, dict) else None})
                    logger.info("Conductor dispatched agent=%s task=%s", agent.id, task.id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Conductor tick failed for agent=%s: %s", agent.id, exc)
                skipped.append({"agent": agent.id, "reason": "exception", "error": str(exc)})

    return {"dispatched": dispatched, "skipped": skipped}
