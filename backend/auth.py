"""Authorization — RBAC with permission-based checks.

Permission codenames follow conventions:
  - Transitions: "transition:{from}:{to}"  (e.g. "transition:backlog:todo")
  - CRUD: "task.create", "task.delete", "project.manage"
  - Special: "*" = wildcard (admin)
"""

from __future__ import annotations
import logging
from sqlalchemy.orm import Session
from backend.models import (
    Profile,
    Permission,
    ProjectMember,
    RolePermission,
    ProfilePermission,
)


logger = logging.getLogger("agentira.auth")

PROJECT_ACCESS_PERMISSIONS = {
    "read": "project.view_all",
    "write": "project.write_all",
    "membership_admin": "project.manage",
}


def get_permissions(db: Session, actor: str) -> set[str]:
    """Get the full set of permission codenames for an actor.

    Union of role permissions + profile-level extra permissions.
    The 'system' actor and system agents (the Conductor, the Concierge)
    get the wildcard '*' — they operate workspace-wide and must see and
    act across every project, not just ones they're a member of.
    """
    # "workflow" is the backend.forge.workflow driver's fixed actor name — a
    # trusted internal caller (not a real profile) that already re-derives
    # its own gate-equivalent checks (see workflow.advance_after_run) before
    # calling TaskService. Same trust level as "system", named separately so
    # the activity trail can tell automated hand-offs apart from manual
    # admin actions.
    if actor in ("system", "workflow"):
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
        (
            db.query(Permission.codename)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .filter(RolePermission.role_id.in_(role_ids))
            .all()
        )
        if role_ids
        else []
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


def project_ids_for_actor(db: Session, actor: str) -> list[str] | None:
    """Return accessible project IDs, or ``None`` for a read-all principal.

    This is deliberately query-oriented so list endpoints can constrain their
    SQL rather than loading protected rows and filtering them in application
    code.
    """
    if has_permission(db, actor, PROJECT_ACCESS_PERMISSIONS["read"]):
        return None
    profile = db.query(Profile).filter(Profile.name == actor).first()
    if not profile:
        return []
    return [
        project_id
        for (project_id,) in (
            db.query(ProjectMember.project_id)
            .filter(ProjectMember.profile_id == profile.id)
            .all()
        )
    ]


def require_project_access(
    db: Session,
    actor: str,
    project_id: str,
    access: str = "read",
) -> None:
    """Enforce the centralized project boundary.

    Membership grants ordinary read/write access. Cross-project access must be
    explicit: ``project.view_all`` for reads, ``project.write_all`` for writes,
    and ``project.manage`` for membership administration. Denials intentionally
    use one non-enumerating message whether the project or membership is absent.
    """
    if access not in PROJECT_ACCESS_PERMISSIONS:
        raise ValueError(f"Unknown project access mode: {access}")

    if has_permission(db, actor, PROJECT_ACCESS_PERMISSIONS[access]):
        return

    profile = db.query(Profile).filter(Profile.name == actor).first()
    is_member = bool(
        profile
        and db.query(ProjectMember.id)
        .filter(
            ProjectMember.project_id == project_id,
            ProjectMember.profile_id == profile.id,
        )
        .first()
    )
    if is_member and access != "membership_admin":
        return

    logger.warning(
        "project_access_denied actor=%r access=%s project_id=%s",
        actor,
        access,
        project_id,
    )
    raise PermissionError("Project resource not found or access denied")


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
