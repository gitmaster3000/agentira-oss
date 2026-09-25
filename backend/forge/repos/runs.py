"""Data access for forge Runs (the per-task run ledger)."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from backend.forge.models import Run, RunOutcome


def prior_run_by_other_agent(db, *, task_id: str, before: datetime,
                             not_agent_id: str) -> Run | None:
    """The most recent run on a task before `before` by a DIFFERENT agent —
    e.g. the implementer whose work a reviewer's run just judged."""
    return (db.query(Run)
              .filter(Run.task_id == task_id,
                      Run.agent_id != not_agent_id,
                      Run.created_at < before)
              .order_by(Run.created_at.desc())
              .first())


def count_agent_runs_since(db, *, task_id: str, agent_id: str,
                           since: datetime) -> int:
    """How many runs an agent has had on a task at/after `since` — the
    bounce/hand-back budget ledger (no extra state; restart-proof)."""
    return (db.query(Run)
              .filter(Run.task_id == task_id,
                      Run.agent_id == agent_id,
                      Run.created_at >= since)
              .count())


def latest_runs_by_task(db, task_ids: Sequence[str]) -> dict[str, Run]:
    """Most recent run per task_id, for the given tasks — one query, no
    N+1. Used by the Conductor picker to tell "run once existed" apart
    from "run is live right now"."""
    if not task_ids:
        return {}
    out: dict[str, Run] = {}
    for r in (db.query(Run)
                .filter(Run.task_id.in_(task_ids))
                .order_by(Run.task_id, Run.created_at.desc())
                .all()):
        out.setdefault(r.task_id, r)
    return out


def count_runs_for_task(db, task_id: str) -> int:
    """Total runs a task has ever had — the auto-redispatch attempt count."""
    return db.query(Run).filter(Run.task_id == task_id).count()


def prior_succeeded_run_by_other_agent(db, *, task_id: str, before: datetime,
                                       not_agent_id: str) -> Run | None:
    """The most recent SUCCEEDED run on a task before `before` by a different
    agent — its presence makes a later run a hand-off (e.g. review), not the
    run that produced the work."""
    return (db.query(Run)
              .filter(Run.task_id == task_id,
                      Run.agent_id != not_agent_id,
                      Run.outcome == RunOutcome.SUCCEEDED,
                      Run.created_at < before)
              .order_by(Run.created_at.desc())
              .first())


def outcomes_for_branch(db, *, task_id: str, branch: str) -> list:
    """Outcomes of the task's runs that worked on `branch`. Empty = no run
    produced that branch (a human/PR-set link)."""
    return [o for (o,) in (db.query(Run.outcome)
                             .filter(Run.task_id == task_id,
                                     Run.worktree_branch == branch)
                             .all())]


def has_active_run(db, task_id: str) -> bool:
    """True while the task has a run starting or in flight (not READY — a
    prepared-but-unstarted run doesn't hold the task)."""
    from backend.forge.models import RunStatus
    return (db.query(Run.id)
              .filter(Run.task_id == task_id,
                      Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING]))
              .first()) is not None
