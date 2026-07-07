"""Data access for the conversation-list views (global /chat + per-agent).
Services compose; repos own the SQL (CLAUDE.md).
"""
from __future__ import annotations


def label_source_names(db, scope_keys) -> tuple[dict[str, str], dict[str, str]]:
    """Batch-resolve the Project names and Task titles referenced by a set of
    conversation scope keys — one query each, instead of a db.get() per scope
    (the N+1 behind the slow global chat list).

    Returns ({project_id: name}, {task_id: title}).
    """
    from backend.models import Project, Task

    project_ids = {
        sk.split(":", 2)[2] for sk in scope_keys if sk.startswith("chat:project:")
    }
    task_ids = {
        sk.split(":", 1)[1] for sk in scope_keys if sk.startswith("task:")
    }
    projects = (
        {pid: name for pid, name in
         db.query(Project.id, Project.name).filter(Project.id.in_(project_ids))}
        if project_ids else {}
    )
    tasks = (
        {tid: title for tid, title in
         db.query(Task.id, Task.title).filter(Task.id.in_(task_ids))}
        if task_ids else {}
    )
    return projects, tasks
