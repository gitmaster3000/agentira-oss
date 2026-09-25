"""Data access for Tasks (the core task row + its run children).

Services compose; repos own the SQL (CLAUDE.md). New task code reads/writes
through here instead of inline `db.query(...)`.
"""

from __future__ import annotations

import os
from typing import Iterable

from backend.models import Epic, Status, Task


def resolve_ref(db, task_ref: str) -> Task | None:
    """Resolve a task by ID or Jira-style key (e.g. 'AP-1')."""
    task = db.get(Task, task_ref)
    if task:
        return task
    return db.query(Task).filter(Task.key == task_ref.upper()).first()


def todo_candidates(db, *, project_id: str, status_id: str,
                    assignee: str) -> list[Task]:
    """Todo tasks assigned to `assignee` in `project_id`, oldest first — the
    Conductor picker's candidate pool, before run-eligibility filtering."""
    return (db.query(Task)
              .filter(Task.project_id == project_id,
                      Task.status_id == status_id,
                      Task.assignee == assignee)
              .order_by(Task.created_at.asc())
              .all())


def unassigned_todo_candidates(db, *, project_ids: Iterable[str],
                               status_id: str, limit: int) -> list[Task]:
    """Unassigned todo tasks across `project_ids`, oldest first, capped at
    `limit` — the planning turn's candidate pool, before run-eligibility
    filtering."""
    return (db.query(Task)
              .filter(Task.project_id.in_(project_ids),
                      Task.status_id == status_id,
                      (Task.assignee == "") | (Task.assignee.is_(None)))
              .order_by(Task.created_at.asc())
              .limit(limit)
              .all())


def backlog_candidates(db, *, project_id: str, status_id: str,
                       limit: int = 30) -> list[Task]:
    """Backlog tasks in `project_id`, oldest first, capped at `limit` — the
    planning turn's promote-to-todo candidate pool (caller ranks by
    priority), before run-eligibility filtering."""
    return (db.query(Task)
              .filter(Task.project_id == project_id,
                      Task.status_id == status_id)
              .order_by(Task.created_at.asc())
              .limit(limit)
              .all())


def _done_status_ids(db) -> set[str]:
    return {s.id for s in db.query(Status).filter(Status.name == "done").all()}


def epic_task_counts(db, epic_id: str) -> tuple[int, int]:
    """(open, done) task counts for an epic — open = any task not in `done`."""
    done_ids = _done_status_ids(db)
    rows = db.query(Task.status_id).filter(Task.epic_id == epic_id).all()
    done = sum(1 for (sid,) in rows if sid in done_ids)
    return len(rows) - done, done


def epics_needing_breakdown(db, project_id: str) -> list[Epic]:
    """In-progress epics committed to the sprint that have no open tasks —
    either none at all, or all of them done. These are what the sprint-
    planning turn breaks down into fresh tasks (C7b)."""
    done_ids = _done_status_ids(db)
    out: list[Epic] = []
    for e in (db.query(Epic)
                .filter(Epic.project_id == project_id,
                        Epic.status == "in_progress")
                .order_by(Epic.created_at.asc())
                .all()):
        rows = db.query(Task.status_id).filter(Task.epic_id == e.id).all()
        if all(sid in done_ids for (sid,) in rows):  # zero open (incl. no tasks)
            out.append(e)
    return out


def project_has_live_work(db, project_id: str) -> bool:
    """True if the project has any task in todo/in_progress/review, or any
    non-terminal run — the "not idle" test for the queue-dry trigger (C7b)."""
    from backend.forge.models import Run, RunStatus

    live_ids = {s.id for s in db.query(Status)
                .filter(Status.name.in_(("todo", "in_progress", "review"))).all()}
    if live_ids and (db.query(Task.id)
                     .filter(Task.project_id == project_id,
                             Task.status_id.in_(live_ids))
                     .first()):
        return True
    non_terminal = [RunStatus.PENDING, RunStatus.RUNNING, RunStatus.PAUSED,
                    RunStatus.READY, RunStatus.INTERRUPTING]
    return (db.query(Run.id)
              .filter(Run.project_id == project_id,
                      Run.status.in_(non_terminal))
              .first()) is not None


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
