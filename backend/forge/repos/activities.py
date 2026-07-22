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


def count_bounce_escalation_comments(db, *, project_id: str,
                                     since: datetime) -> int:
    """Count of workflow bounce/needs-attention comments on `project_id`'s
    task feed since `since` — the sprint review's systemic-issue signal.
    Both share `action == "commented"`; distinguished by their detail
    marker text (see forge/workflow.py `_bounce_gate_failure`)."""
    from sqlalchemy import or_
    return (db.query(Activity)
              .filter(Activity.project_id == project_id,
                      Activity.actor == "workflow",
                      Activity.action == "commented",
                      Activity.created_at >= since,
                      or_(Activity.detail.ilike("%Bounced back%"),
                          Activity.detail.ilike("%Needs attention%")))
              .count())


def add_task_comment(db, *, project_id: str, task_id: str,
                     detail: str, actor: str = "workflow") -> None:
    """Post a comment on the task feed. Caller owns the commit."""
    db.add(Activity(project_id=project_id, task_id=task_id, actor=actor,
                    action="commented", detail=detail))
