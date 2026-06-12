"""Data access for the Activity ledger (task feed / audit trail)."""

from __future__ import annotations

from datetime import datetime

from backend.models import Activity


def task_moves_since(db, *, task_id: str, since: datetime) -> list[Activity]:
    """Status-move rows on a task, newest first, logged at/after `since`."""
    return (db.query(Activity)
              .filter(Activity.task_id == task_id,
                      Activity.action == "task.move",
                      Activity.created_at >= since)
              .order_by(Activity.created_at.desc())
              .all())


def latest_comment_by(db, *, task_id: str, actor: str,
                      since: datetime) -> Activity | None:
    """The actor's most recent comment on a task at/after `since`."""
    return (db.query(Activity)
              .filter(Activity.task_id == task_id,
                      Activity.action == "commented",
                      Activity.actor == actor,
                      Activity.created_at >= since)
              .order_by(Activity.created_at.desc())
              .first())


def add_task_comment(db, *, project_id: str, task_id: str,
                     detail: str, actor: str = "workflow") -> None:
    """Post a comment on the task feed. Caller owns the commit."""
    db.add(Activity(project_id=project_id, task_id=task_id, actor=actor,
                    action="commented", detail=detail))
