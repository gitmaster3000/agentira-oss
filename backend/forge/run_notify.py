"""Structured metadata for run notifications.

The Inbox / bell render a rich row (agent, task, project, status pills) from
this blob; `title` stays as the plain-text fallback for legacy rows.
"""
from __future__ import annotations

from backend.models import Project, Task


def run_meta(db, run, agent, *, status: str, error: str | None = None) -> dict:
    task = db.get(Task, run.task_id) if run.task_id else None
    project = db.get(Project, run.project_id) if run.project_id else None
    meta = {
        "kind": "run",
        "status": status,  # created | ready | running | completed | failed
        "agent_name": agent.name if agent else "Agent",
        "task_key": task.key if task else None,
        "task_title": task.title if task else None,
        "project_name": project.name if project else None,
        "model": run.model_used or None,
    }
    if status in ("completed", "failed"):
        meta["duration_ms"] = run.duration_ms
        meta["cost_usd"] = run.cost_usd or 0.0
        meta["pr_url"] = (task.pr_url or None) if task else None
    if error:
        meta["error"] = error[:200]
    return {k: v for k, v in meta.items() if v is not None}
