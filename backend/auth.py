"""Authorization — RBAC with permission-based checks.

Permission codenames follow conventions:
  - Transitions: "transition:{from}:{to}"  (e.g. "transition:backlog:todo")
  - CRUD: "task.create", "task.delete", "project.manage"
  - Special: "*" = wildcard (admin)
"""

from __future__ import annotations
from sqlalchemy.orm import Session
from backend.models import Profile, Permission, RolePermission, ProfilePermission


def get_permissions(db: Session, actor: str) -> set[str]:
    """Get the full set of permission codenames for an actor.

    Union of role permissions + profile-level extra permissions.
    'system' actor gets wildcard '*'.
    """
    if actor == "system":
        return {"*"}

    profile = db.query(Profile).filter(Profile.name == actor).first()
    if not profile:
        return set()

    # Role permissions
    role_perms = (
        db.query(Permission.codename)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .filter(RolePermission.role_id == profile.role_id)
        .all()
    )

    # Extra profile-level permissions
    profile_perms = (
        db.query(Permission.codename)
        .join(ProfilePermission, ProfilePermission.permission_id == Permission.id)
        .filter(ProfilePermission.profile_id == profile.id)
        .all()
    )

    return {p[0] for p in role_perms} | {p[0] for p in profile_perms}


def has_permission(db: Session, actor: str, codename: str) -> bool:
    """Check if an actor has a specific permission."""
    perms = get_permissions(db, actor)
    return "*" in perms or codename in perms


def check_transition(db: Session, actor: str, from_status: str, to_status: str) -> None:
    """Validate a status transition. Raises PermissionError if denied."""
    if from_status == to_status:
        return

    perms = get_permissions(db, actor)
    if "*" in perms or "transition:*" in perms:
        return

    codename = f"transition:{from_status}:{to_status}"
    if codename not in perms:
        raise PermissionError(
            f"'{actor}' lacks permission '{codename}' to move from '{from_status}' to '{to_status}'."
        )
