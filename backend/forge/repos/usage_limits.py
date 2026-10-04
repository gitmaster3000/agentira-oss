"""Data access for usage-limit pauses (runtime gate + paused runs)."""

from __future__ import annotations

from datetime import datetime

from backend.forge.models import Agent, ForgeRuntime, Run, RunStatus

PAUSE_REASON = "usage_limit"


def get_run(db, run_id: str) -> Run | None:
    return db.query(Run).filter(Run.id == run_id).first()


def get_runtime(db, runtime_id: str) -> ForgeRuntime | None:
    return db.get(ForgeRuntime, runtime_id)


def runtime_for_agent(db, agent_id: str) -> ForgeRuntime | None:
    agent = db.get(Agent, agent_id)
    return db.get(ForgeRuntime, agent.runtime_id) if agent and agent.runtime_id else None


def limited_runtime_ids(db, now: datetime) -> set[str]:
    """Runtimes whose usage limit has not yet reset."""
    rows = (db.query(ForgeRuntime.id)
              .filter(ForgeRuntime.limited_until.isnot(None),
                      ForgeRuntime.limited_until > now)
              .all())
    return {r[0] for r in rows}


def due_paused_runs(db, now: datetime) -> list[Run]:
    """Limit-paused runs whose resume_at has passed, oldest first."""
    return (db.query(Run)
              .filter(Run.status == RunStatus.PAUSED,
                      Run.pause_reason == PAUSE_REASON,
                      Run.resume_at.isnot(None),
                      Run.resume_at <= now)
              .order_by(Run.resume_at)
              .all())
