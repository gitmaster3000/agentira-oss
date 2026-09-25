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


def list_runs(db, *, scope, project_ids=None, agent_id: str | None = None,
              project_id: str | None = None, status: str | None = None,
              outcome: str | None = None, unresolved: bool = False,
              limit: int = 100, offset: int = 0) -> list[Run]:
    """The Runs list, newest first. `scope` is the caller's org filter;
    `project_ids` (None = no restriction) the actor's visible projects.

    `unresolved` (AP-509) drops runs whose verdict was overtaken — the task is
    done, another run on the task started after this one finished, or the
    human dismissed it — so a needs_input question stops showing once it's
    resolved elsewhere."""
    from sqlalchemy import exists, func, or_
    from sqlalchemy.orm import aliased
    from backend.models import Status, Task
    q = db.query(Run)
    if project_ids is not None:
        q = q.filter(Run.project_id.in_(project_ids))
    if agent_id:
        q = q.filter(Run.agent_id == agent_id)
    if project_id:
        q = q.filter(Run.project_id == project_id)
    if status:
        q = q.filter(Run.status == status)
    if outcome:
        q = q.filter(Run.outcome == outcome)
    if unresolved:
        later = aliased(Run)
        q = q.filter(~exists().where(
            Task.id == Run.task_id, Task.status_id == Status.id,
            Status.name == "done"))
        q = q.filter(~exists().where(
            later.task_id == Run.task_id, later.id != Run.id,
            later.started_at > func.coalesce(Run.finished_at, Run.created_at)))
        q = q.filter(or_(
            Run.question_dismissed_at.is_(None),
            Run.question_dismissed_at < func.coalesce(Run.finished_at, Run.created_at)))
    # AP-190: one row per (agent, task); exclude throwaway shadow rows.
    q = q.filter(Run.trigger_event != "chat.shadow").filter(scope)
    return q.order_by(Run.created_at.desc()).offset(offset).limit(limit).all()


def dismiss_question(db, run_id: str) -> Run | None:
    """AP-509: stamp the human's dismissal of the run's "Needs you" question."""
    from datetime import timezone
    run = db.get(Run, run_id)
    if run is not None:
        run.question_dismissed_at = datetime.now(timezone.utc)
        db.commit()
    return run
