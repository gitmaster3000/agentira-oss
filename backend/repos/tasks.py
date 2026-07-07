"""Data access for the Task listing/serialization path (board, backlog,
roadmap). Services compose; repos own the SQL (CLAUDE.md).
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Query, selectinload

from backend.models import Task, TaskCommit


def with_list_relations(query: Query) -> Query:
    """Eager-load epic/status onto a Task query. Without this, serializing
    N tasks fires 2N extra SELECTs (default lazy='select' on both
    relationships) — the N+1 behind the slow board/backlog/roadmap loads."""
    return query.options(selectinload(Task.epic), selectinload(Task.status))


def batch_commit_counts(db, task_ids: list[str]) -> dict[str, int]:
    """{task_id: count}, one aggregate query — replaces the per-row
    `len(t.commits)` lazy-load."""
    if not task_ids:
        return {}
    rows = (
        db.query(TaskCommit.task_id, func.count(TaskCommit.id))
        .filter(TaskCommit.task_id.in_(task_ids))
        .group_by(TaskCommit.task_id)
        .all()
    )
    return {task_id: count for task_id, count in rows}
