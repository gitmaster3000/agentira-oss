"""Data access for forge Runs (the per-task run ledger)."""

from __future__ import annotations

from datetime import datetime

from backend.forge.models import Run


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
