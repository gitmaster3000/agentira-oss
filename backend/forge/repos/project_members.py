"""Data access for project membership rows used by orchestration code."""

from __future__ import annotations

from backend.models import ProjectMember


def ensure_member(db, *, project_id: str, profile_id: str,
                  org_id: str | None) -> bool:
    """Add `profile_id` to `project_id` if absent. Returns True when a row
    was added. Caller owns the commit. `org_id` is set explicitly so this
    works from org-free (scheduler) sessions too."""
    exists = (db.query(ProjectMember.id)
                .filter(ProjectMember.project_id == project_id,
                        ProjectMember.profile_id == profile_id)
                .first())
    if exists:
        return False
    db.add(ProjectMember(project_id=project_id, profile_id=profile_id,
                         org_id=org_id))
    db.flush()
    return True
