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
    The 'system' actor and system agents (the Conductor, the Concierge)
    get the wildcard '*' — they operate workspace-wide and must see and
    act across every project, not just ones they're a member of.
    """
    if actor == "system":
        return {"*"}

    profile = db.query(Profile).filter(Profile.name == actor).first()
    if not profile:
        return set()

    # System agents are seeded by Agentira to orchestrate / guide the
    # whole workspace — scoping them to project memberships would blind
    # them (the Conductor's `list_projects` returned []). Full perms.
    if getattr(profile, "is_system", False):
        return {"*"}

    # Role permissions — union across ALL of the profile's roles (RBAC M2M).
    role_ids = [r.id for r in profile.roles]
    role_perms = (
        db.query(Permission.codename)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .filter(RolePermission.role_id.in_(role_ids))
        .all()
    ) if role_ids else []

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
