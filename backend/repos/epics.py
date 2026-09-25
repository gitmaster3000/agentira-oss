"""Data access for epics. Services compose; repos own the SQL (CLAUDE.md)."""
from __future__ import annotations

from backend.models import Epic, Status, Task


def get(db, epic_id: str) -> Epic | None:
    return db.get(Epic, epic_id)


def task_status_pairs(db, epic_id: str) -> list[tuple[str, str]]:
    """[(task_key_or_id, status_name)] for every task in the epic."""
    rows = (
        db.query(Task.key, Task.id, Status.name)
        .join(Status, Task.status_id == Status.id)
        .filter(Task.epic_id == epic_id)
        .all()
    )
    return [(key or task_id, status_name) for key, task_id, status_name in rows]
