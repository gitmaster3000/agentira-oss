"""Data access for Tasks (the core task row + its run children).

Services compose; repos own the SQL (CLAUDE.md). New task code reads/writes
through here instead of inline `db.query(...)`.
"""

from __future__ import annotations

import os

from backend.models import Task


def resolve_ref(db, task_ref: str) -> Task | None:
    """Resolve a task by ID or Jira-style key (e.g. 'AP-1')."""
    task = db.get(Task, task_ref)
    if task:
        return task
    return db.query(Task).filter(Task.key == task_ref.upper()).first()


def delete_with_children(db, task: Task) -> None:
    """Delete a task and its dependent rows in one transaction (no commit).

    `activities`, `attachments`, and `commits` already cascade via the ORM
    relationships on Task. The gap is `forge_runs.task_id`: it has no cascade,
    so a task that's been worked by an agent has a Run row that blocks the
    delete with an IntegrityError (the AP-284 500). Runs are 1:1 with tasks and
    nothing references `forge_runs.id`, so hard-delete them first.
    """
    from backend.forge.models import Run

    db.query(Run).filter(Run.task_id == task.id).delete(synchronize_session=False)

    # Attachment ROWS cascade via the ORM relationship, but the files on disk
    # would be orphaned — remove them while we still have the paths.
    for att in task.attachments:
        if att.file_path and os.path.exists(att.file_path):
            try:
                os.remove(att.file_path)
            except OSError:
                pass  # best-effort; a missing/locked file must not block delete

    db.delete(task)
