"""Data access for global search. Services compose; repos own the SQL.

Each function takes the session plus the caller's accessible project ids
(``None`` = read-all principal, see ``backend.auth.project_ids_for_actor``).
"""
from __future__ import annotations

from sqlalchemy import or_

from backend.models import Epic, Project, Task
from backend.forge.models import Agent


def _like(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_projects(db, q, project_ids, limit):
    query = db.query(Project).filter(or_(
        Project.name.ilike(_like(q), escape="\\"),
        Project.key_prefix.ilike(_like(q), escape="\\"),
    ))
    if project_ids is not None:
        query = query.filter(Project.id.in_(project_ids))
    return query.order_by(Project.name).limit(limit).all()


def search_tasks(db, q, project_ids, limit):
    query = db.query(Task).filter(or_(
        Task.title.ilike(_like(q), escape="\\"),
        Task.key.ilike(_like(q), escape="\\"),
    ))
    if project_ids is not None:
        query = query.filter(Task.project_id.in_(project_ids))
    return query.order_by(Task.updated_at.desc()).limit(limit).all()


def search_epics(db, q, project_ids, limit):
    query = db.query(Epic).filter(Epic.title.ilike(_like(q), escape="\\"))
    if project_ids is not None:
        query = query.filter(Epic.project_id.in_(project_ids))
    return query.order_by(Epic.created_at.desc()).limit(limit).all()


def search_agents(db, q, limit):
    return (
        db.query(Agent).filter(Agent.name.ilike(_like(q), escape="\\"))
        .order_by(Agent.name).limit(limit).all()
    )


def project_names(db, project_ids) -> dict[str, str]:
    if not project_ids:
        return {}
    rows = db.query(Project.id, Project.name).filter(Project.id.in_(project_ids)).all()
    return {pid: name for pid, name in rows}
