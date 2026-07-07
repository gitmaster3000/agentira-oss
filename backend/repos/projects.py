"""Data access for the Project domain.

Starts the core repo layer with the queries the delete-cascade needs.
`project_repos` rows and the `Profile.default_project_id` pointer carry no ORM
cascade, so they must be cleared explicitly before `db.delete(project)`.
Other project reads still live in services.py (legacy) — migrate as touched.
"""
from __future__ import annotations

from sqlalchemy import func

from backend.models import ProjectRepo, Profile, Task


def delete_project_repos(db, project_id: str) -> None:
    db.query(ProjectRepo).filter(ProjectRepo.project_id == project_id).delete(
        synchronize_session=False)


def clear_default_project_pointers(db, project_id: str) -> None:
    db.query(Profile).filter(Profile.default_project_id == project_id).update(
        {Profile.default_project_id: None}, synchronize_session=False)


def task_counts_by_project(db, project_ids: list[str]) -> dict[str, int]:
    """One aggregate COUNT for all given projects, instead of a per-project
    `len(p.tasks)` lazy-load (perf fix — list_projects was N+1)."""
    if not project_ids:
        return {}
    rows = (
        db.query(Task.project_id, func.count(Task.id))
        .filter(Task.project_id.in_(project_ids))
        .group_by(Task.project_id)
        .all()
    )
    return {project_id: count for project_id, count in rows}
