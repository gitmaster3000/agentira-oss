"""Data access for the Project domain.

Starts the core repo layer with the queries the delete-cascade needs.
`project_repos` rows and the `Profile.default_project_id` pointer carry no ORM
cascade, so they must be cleared explicitly before `db.delete(project)`.
Other project reads still live in services.py (legacy) — migrate as touched.
"""
from __future__ import annotations

from backend.models import ProjectRepo, Profile


def delete_project_repos(db, project_id: str) -> None:
    db.query(ProjectRepo).filter(ProjectRepo.project_id == project_id).delete(
        synchronize_session=False)


def clear_default_project_pointers(db, project_id: str) -> None:
    db.query(Profile).filter(Profile.default_project_id == project_id).update(
        {Profile.default_project_id: None}, synchronize_session=False)
