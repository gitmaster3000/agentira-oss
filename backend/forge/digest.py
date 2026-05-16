"""AP-84 Digest — overnight run summary for a project.

Aggregates Run rows (by outcome + status) and Activity rows for a window.
Powers a dashboard panel so the user can see what their agents did while
they slept. Email/Slack delivery is out of scope for v1.

Single entry point: `generate_digest(project_id, since_ts) -> dict`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from backend.db import SessionLocal
from backend.models import Project, Task, Activity
from backend.forge.models import Run, RunStatus, RunOutcome


def _parse_since(since: str | datetime) -> datetime:
    if isinstance(since, datetime):
        return since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    # Accept "24h", "7d", or ISO timestamp.
    s = since.strip()
    if s.endswith("h") and s[:-1].isdigit():
        return datetime.now(timezone.utc) - timedelta(hours=int(s[:-1]))
    if s.endswith("d") and s[:-1].isdigit():
        return datetime.now(timezone.utc) - timedelta(days=int(s[:-1]))
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _run_to_card(r: Run, task: Task | None) -> dict:
    return {
        "id": r.id,
        "agent_id": r.agent_id,
        "task_id": r.task_id,
        "task_title": task.title if task else "",
        "task_key": (task.key if task else "") or "",
        "outcome": r.outcome.value if r.outcome else None,
        "status": r.status.value if r.status else None,
        "summary": (r.summary or "")[:400],
        "duration_ms": r.duration_ms or 0,
        "cost_usd": float(r.cost_usd or 0),
        "input_tokens": int(r.input_tokens or 0),
        "output_tokens": int(r.output_tokens or 0),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


def generate_digest(*, project_id: str, since: str | datetime = "24h") -> dict:
    """Aggregate runs and activity for `project_id` since `since`.

    Returns a structured digest used by the dashboard panel and (later)
    the email/Slack senders. Numbers come from real Run/Activity tables —
    no parallel state.
    """
    since_dt = _parse_since(since)
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if not project:
            return {"error": "project_not_found"}

        # All tasks in this project — used to map run.task_id → task title
        # and to constrain the run window to project work.
        task_rows = db.query(Task).filter(Task.project_id == project_id).all()
        task_ids = {t.id for t in task_rows}
        task_by_id = {t.id: t for t in task_rows}

        # Runs finished in the window AND tied to a task in this project.
        # (Free-form runs without a task_id don't appear in a project digest.)
        runs = (db.query(Run)
                  .filter(Run.task_id.in_(task_ids) if task_ids else False,
                          Run.finished_at >= since_dt)
                  .order_by(Run.finished_at.desc())
                  .all())

        succeeded = [r for r in runs if r.outcome == RunOutcome.SUCCEEDED]
        blocked = [r for r in runs if r.outcome == RunOutcome.BLOCKED]
        needs_input = [r for r in runs if r.outcome == RunOutcome.NEEDS_INPUT]
        failed = [r for r in runs
                  if r.outcome == RunOutcome.FAILED
                  or (r.status == RunStatus.FAILED and r.outcome is None)]

        # Currently in-flight runs in this project (not bounded by since_ts —
        # an in-flight run that started before the window is still in-flight).
        in_flight = (db.query(Run)
                       .filter(Run.task_id.in_(task_ids) if task_ids else False,
                               Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING,
                                               RunStatus.PAUSED]))
                       .order_by(Run.created_at.desc())
                       .all())

        total_cost = sum(float(r.cost_usd or 0) for r in runs)
        total_in = sum(int(r.input_tokens or 0) for r in runs)
        total_out = sum(int(r.output_tokens or 0) for r in runs)

        # Activity counts since the window — gives a board-movement view.
        # Activity already orders by created_at.desc; we just filter by time.
        activity_rows = (db.query(Activity)
                           .filter(Activity.project_id == project_id,
                                   Activity.created_at >= since_dt)
                           .all())
        action_counts: dict[str, int] = {}
        for a in activity_rows:
            action_counts[a.action] = action_counts.get(a.action, 0) + 1

    def cards(rs):
        return [_run_to_card(r, task_by_id.get(r.task_id)) for r in rs]

    return {
        "project": {"id": project.id, "name": project.name},
        "window": {"since": since_dt.isoformat(), "until": now.isoformat()},
        "counts": {
            "done": len(succeeded),
            "blocked": len(blocked),
            "needs_input": len(needs_input),
            "failed": len(failed),
            "in_flight": len(in_flight),
            "total_runs": len(runs),
        },
        "stats": {
            "cost_usd": round(total_cost, 4),
            "input_tokens": total_in,
            "output_tokens": total_out,
        },
        "done": cards(succeeded),
        "blocked": cards(blocked),
        "needs_input": cards(needs_input),
        "failed": cards(failed),
        "in_flight": cards(in_flight),
        "activity_counts": action_counts,
    }
