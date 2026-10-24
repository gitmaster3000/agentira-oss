"""Data access for the work snapshot — every read the night snapshot needs.
Services compose; repos own the SQL (CLAUDE.md). Functions take a session.

`project_ids` is the set of projects to look at; every query is constrained
by it in SQL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import func

from backend.forge.models import (Agent, ForgeRuntime, Run, RunOutcome,
                                  RunStatus)
from backend.models import Project, Status, Task

_LIVE = (RunStatus.PENDING, RunStatus.RUNNING, RunStatus.PAUSED)
_FAILED_ENDINGS = (RunStatus.FAILED, RunStatus.CANCELLED)


def projects(db, *, project_id: str | None,
             allowed_ids: Sequence[str] | None) -> list[Project]:
    """Projects in scope: one project, or all — narrowed to `allowed_ids`
    (None = no narrowing)."""
    q = db.query(Project)
    if project_id:
        q = q.filter(Project.id == project_id)
    if allowed_ids is not None:
        q = q.filter(Project.id.in_(list(allowed_ids)))
    return q.order_by(Project.name).all()


def tasks_in_status_since(db, *, project_ids: Sequence[str], status: str,
                          since: datetime) -> list[Task]:
    """Tasks currently in `status` that got there in the window (done:
    completed_at, falling back to updated_at)."""
    stamp = func.coalesce(Task.completed_at, Task.updated_at)
    return (db.query(Task).join(Status, Task.status_id == Status.id)
              .filter(Task.project_id.in_(list(project_ids)),
                      Status.name == status, stamp >= since)
              .order_by(stamp.desc()).all())


def runs_finished_since(db, *, project_ids: Sequence[str],
                        since: datetime) -> list[tuple[Run, Task]]:
    return (db.query(Run, Task).join(Task, Run.task_id == Task.id)
              .filter(Task.project_id.in_(list(project_ids)),
                      Run.finished_at >= since)
              .order_by(Run.finished_at.desc()).all())


def live_runs(db, *, project_ids: Sequence[str]) -> list[tuple[Run, Task]]:
    return (db.query(Run, Task).join(Task, Run.task_id == Task.id)
              .filter(Task.project_id.in_(list(project_ids)),
                      Run.status.in_(_LIVE))
              .order_by(Run.created_at.desc()).all())


def unanswered_question_runs(db, *, project_ids: Sequence[str]
                             ) -> list[tuple[Run, Task]]:
    """Runs whose outcome is blocked / needs_input, on a task that is not
    done, that no later run has followed up and the human has not dismissed."""
    rows = (db.query(Run, Task).join(Task, Run.task_id == Task.id)
              .join(Status, Task.status_id == Status.id)
              .filter(Task.project_id.in_(list(project_ids)),
                      Status.name != "done",
                      Run.outcome.in_([RunOutcome.BLOCKED,
                                       RunOutcome.NEEDS_INPUT]))
              .order_by(Run.created_at.desc()).all())
    latest = _latest_per_task(db, [t.id for _, t in rows])
    return [(r, t) for r, t in rows
            if latest.get(t.id) is not None and latest[t.id].id == r.id
            and not (r.question_dismissed_at
                     and r.finished_at
                     and r.question_dismissed_at >= r.finished_at)]


def _latest_per_task(db, task_ids: Sequence[str]) -> dict[str, Run]:
    from backend.forge.repos import runs as runs_repo
    return runs_repo.latest_runs_by_task(db, task_ids)


def tasks_with_spent_retries(db, *, project_ids: Sequence[str],
                             max_attempts: int) -> list[tuple[Run, Task]]:
    """Open tasks whose latest run failed/was cancelled and whose
    auto-redispatch budget (`max_attempts` runs) is used up."""
    spent = (db.query(Run.task_id)
               .filter(Run.task_id.isnot(None))
               .group_by(Run.task_id)
               .having(func.count(Run.id) >= max_attempts)
               .subquery())
    cand = (db.query(Task).join(Status, Task.status_id == Status.id)
              .filter(Task.project_id.in_(list(project_ids)),
                      Task.id.in_(db.query(spent.c.task_id)),
                      Status.name.notin_(["done", "review"])).all())
    latest = _latest_per_task(db, [t.id for t in cand])
    return [(latest[t.id], t) for t in cand
            if t.id in latest and latest[t.id].status in _FAILED_ENDINGS]


def stale_runtimes(db, *, cutoff: datetime) -> list[ForgeRuntime]:
    """Runtimes that serve at least one agent but have not heartbeated since
    `cutoff` (never-heartbeated ones count only if they claim to be online)."""
    from backend.forge.models import RuntimeStatus
    served = db.query(Agent.runtime_id).filter(Agent.runtime_id.isnot(None))
    return (db.query(ForgeRuntime)
              .filter(ForgeRuntime.id.in_(served),
                      (ForgeRuntime.last_heartbeat < cutoff)
                      | ((ForgeRuntime.last_heartbeat.is_(None))
                         & ForgeRuntime.status.in_([RuntimeStatus.ONLINE,
                                                    RuntimeStatus.BUSY])))
              .order_by(ForgeRuntime.last_heartbeat).all())


def last_daemon_heartbeat(db) -> datetime | None:
    return db.query(func.max(ForgeRuntime.last_heartbeat)).scalar()
