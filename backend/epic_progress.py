"""Close an epic when its last task reaches done (Loop v1 C7c).

Deterministic done-handler helper: ``move_task`` calls this whenever a task
lands in ``done``. If every task in that task's epic is now done and the epic
isn't already closed, the epic is set to ``done`` with an activity line listing
the shipped task keys.

The trigger is a task→done transition, not a poll: an epic a human reopens
(with all its tasks already done) stays open until another task transitions to
done.
"""
from __future__ import annotations

from backend import services
from backend.repos import epics as epics_repo

# Terminal status name — the same check the board/roadmap use (t.status.name
# == "done"). Not a new status-name list.
_DONE = "done"


def close_epic_if_complete(task_id: str, actor: str = "system") -> bool:
    """If ``task_id``'s epic has no open tasks left, close it. Returns True
    when the epic was closed by this call."""
    from backend.models import Task

    with services._session() as db:
        task = db.get(Task, task_id)
        if not task or not task.epic_id:
            return False
        epic = epics_repo.get(db, task.epic_id)
        if not epic or epic.status == _DONE:
            return False

        pairs = epics_repo.task_status_pairs(db, epic.id)
        if not pairs or any(name != _DONE for _, name in pairs):
            return False

        shipped = ", ".join(key for key, _ in pairs)
        epic.status = _DONE
        services._log_activity(
            db, actor, "epic.done",
            f"All tasks done — epic closed. Shipped: {shipped}",
            project_id=epic.project_id,
        )
        db.commit()
        return True
