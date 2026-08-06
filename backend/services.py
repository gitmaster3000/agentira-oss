"""Facade service — all business logic lives here.

Both REST API and MCP server call into this layer.
"""

from __future__ import annotations
from datetime import datetime as _dt, timezone as _tz
from typing import Optional
from sqlalchemy.orm import Session, selectinload

from backend.db import SessionLocal, init_db, privileged, set_current_org, _derive_account_type
from backend.models import (
    Project, Task, Activity, Profile, Attachment,
    Role, Permission, RolePermission, ProfilePermission, Status,
    ProjectMember, Notification, TaskCommit, Epic, OAuthAccount, Org
)
from backend.auth import has_permission, project_ids_for_actor, require_project_access
from backend.notifications import broker
from backend import agent_notifier
from backend.deploy.manager import DeploymentManager
from backend.deploy.flow import DeployFlow

import logging
import os
import secrets

from backend import passwords

logger = logging.getLogger("agentira.services")


def authorize_project_access(
    project_id: str,
    actor: str,
    access: str = "read",
) -> None:
    """Public boundary helper for routes that delegate outside this module."""
    with _session() as db:
        require_project_access(db, actor, project_id, access)


def authorize_task_access(
    task_id: str,
    actor: str,
    access: str = "read",
) -> Task:
    """Resolve a direct task reference and enforce its owning project."""
    with _session() as db:
        task = _resolve_task(db, task_id)
        if not task:
            raise ValueError("Task not found")
        require_project_access(db, actor, task.project_id, access)
        return task


def authorize_epic_access(
    epic_id: str,
    actor: str,
    access: str = "read",
) -> Epic:
    """Resolve a direct epic reference and enforce its owning project."""
    with _session() as db:
        epic = db.get(Epic, epic_id)
        if not epic:
            raise ValueError("Epic not found")
        require_project_access(db, actor, epic.project_id, access)
        return epic


def authorize_attachment_access(
    attachment_id: str,
    actor: str,
    access: str = "read",
) -> Attachment:
    """Resolve any attachment shape to its project before authorization."""
    with _session() as db:
        attachment = db.get(Attachment, attachment_id)
        if not attachment:
            raise ValueError("Attachment not found")
        if attachment.project_id:
            project_id = attachment.project_id
        elif attachment.task_id:
            task = db.get(Task, attachment.task_id)
            project_id = task.project_id if task else None
        elif attachment.epic_id:
            epic = db.get(Epic, attachment.epic_id)
            project_id = epic.project_id if epic else None
        else:
            project_id = None
        if not project_id:
            raise PermissionError("Project resource not found or access denied")
        require_project_access(db, actor, project_id, access)
        return attachment

def _hash_password(password: str) -> str:
    """Hash a password for storage (bcrypt — AP-194)."""
    return passwords.hash_password(password)

def authenticate_user(username: str, password: str) -> dict | None:
    """Verify credentials and return profile dict.

    Transparently migrates legacy unsalted SHA-256 hashes to bcrypt on a
    successful login (AP-194), so the old scheme drains without a reset."""
    # Login is cross-org: we don't know the user's org until we find them.
    # Identifier is the username (name) or, failing that, the email (stored
    # lowercased) — admins hand out emails, so people log in with them too.
    with privileged(), _session() as db:
        p = db.query(Profile).filter(Profile.name == username).first()
        if not p and "@" in username:
            p = db.query(Profile).filter(Profile.email == username.strip().lower()).first()
        if not p:
            return None
        if not passwords.verify_password(password, p.password_hash or ""):
            return None
        if passwords.needs_rehash(p.password_hash or ""):
            p.password_hash = passwords.hash_password(password)
            db.commit()
        return _profile_to_dict(p)

# ── Helpers ──────────────────────────────────────────────────────────────

def _session() -> Session:
    return SessionLocal()


def _parse_dod(raw: str | None) -> list | None:
    if not raw:
        return None
    import json as _json
    try:
        return _json.loads(raw)
    except Exception:
        return []


def _normalize_dod(items: list | None) -> list[dict] | None:
    """Coerce DoD items to the canonical {text, checked} shape.

    Accepts a plain string (-> unchecked item) or a dict (text/label +
    checked). A robust gate: a stray string from a caller must never be
    persisted raw nor crash a read. Used on both write and read paths, so
    legacy malformed rows heal on the next read without a migration.
    """
    if not items:
        return None
    out: list[dict] = []
    for it in items:
        if isinstance(it, str):
            out.append({"text": it, "checked": False})
        elif isinstance(it, dict):
            out.append({
                "text": it.get("text") or it.get("label") or "",
                "checked": bool(it.get("checked")),
            })
        # anything else (None, numbers) is not a valid DoD item — drop it
    return out or None


def _dod_progress(dod: list | None) -> dict | None:
    if not dod:
        return None
    total = len(dod)
    # Defensive: a non-dict item (legacy/malformed row) counts as unchecked
    # rather than crashing the whole task list.
    checked = sum(1 for item in dod if isinstance(item, dict) and item.get("checked"))
    return {"total": total, "checked": checked}


def _resolve_task(db: Session, task_ref: str) -> Task | None:
    """Resolve a task by ID or Jira-style key (e.g. 'AGNT-1')."""
    task = db.get(Task, task_ref)
    if task:
        return task
    return db.query(Task).filter(Task.key == task_ref.upper()).first()


def _task_to_dict(t: Task, attachments_count: int = 0, commits_count: int | None = None) -> dict:
    dod = _normalize_dod(_parse_dod(t.dod_items))
    return {
        "id": t.id,
        "key": t.key or t.id,
        "type": t.type or "task",
        "project_id": t.project_id,
        "epic_id": t.epic_id,
        # AP-496: task-graph pointers. `subtasks`/`blocked_by`/`blocks` are
        # filled in by the batched annotators (task_graph) on the list/get
        # paths — defaulted here so every serialized task has the same shape.
        "parent_id": t.parent_id,
        "milestone_id": t.milestone_id,
        "subtasks": {"total": 0, "done": 0},
        "blocked_by": [],
        "blocks": [],
        "is_blocked": False,
        "epic_name": t.epic.title if t.epic else None,
        "epic_color": t.epic.color if t.epic else None,
        "title": t.title,
        "description": t.description,
        "status": t.status.name,
        "priority": t.priority.value,
        "assignee": t.assignee,
        "creator": t.creator,
        "tags": [tag.strip() for tag in t.tags.split(",") if tag.strip()] if t.tags else [],
        "start_date": t.start_date.isoformat() if t.start_date else None,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "dod_items": dod,
        "dod_progress": _dod_progress(dod),
        "branch": t.branch or "",
        "pr_url": t.pr_url or "",
        "commits_count": commits_count if commits_count is not None else (len(t.commits) if t.commits else 0),
        # AP-154: surface the resolved repo list to clients. Multi-select
        # UI reads this; legacy single-repo callers still get `repo_name`.
        "repo_name": t.repo_name or "",
        "repos": resolve_task_repos(t),
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
        "attachments_count": attachments_count,
        # AP-184/185: is an agent actively executing on this task right now (a
        # run in pending/running/interrupting)? Drives the "working" glow +
        # indicator. active_agent_id/name name the agent so the indicator can
        # link to its task chat. Set by list_tasks/get_task; defaults below.
        "agent_active": False,
        "active_agent_id": None,
        "active_agent_name": None,
    }


def _active_run_agents(db, task_ids: list[str]) -> dict[str, dict]:
    """task_id -> {agent_id, agent_name} for the latest live run (a run in
    pending/running/interrupting). Batched so the board doesn't N+1. Forge is
    optional — never break task listing if it's unavailable."""
    if not task_ids:
        return {}
    try:
        from backend.forge.models import Run, RunStatus, Agent as _FA
        rows = (db.query(Run.task_id, Run.agent_id, _FA.name)
                  .outerjoin(_FA, _FA.id == Run.agent_id)
                  .filter(Run.task_id.in_(task_ids),
                          Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING,
                                          RunStatus.INTERRUPTING]))
                  .order_by(Run.created_at.desc()).all())
        out: dict[str, dict] = {}
        for tid, aid, aname in rows:
            if tid and tid not in out:
                out[tid] = {"agent_id": aid, "agent_name": aname}
        return out
    except Exception:  # noqa: BLE001
        return {}


def resolve_task_repos(t: Task) -> list[str]:
    """AP-154: return the list of project_repos.name values this task
    targets.

    Order of preference:
    1. `Task.repos_json` (the new multi-repo column) if set + parseable.
    2. `Task.repo_name` (legacy single-repo) → wrapped as a one-item list.
    3. Empty list → daemon falls back to the project's primary repo.
    """
    import json as _json
    if t.repos_json:
        try:
            parsed = _json.loads(t.repos_json)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x]
        except Exception:  # noqa: BLE001
            pass
    if t.repo_name:
        return [t.repo_name]
    return []


def _batch_attachment_counts(db: Session, task_ids: list[str]) -> dict[str, int]:
    """Return {task_id: count} for all given task IDs in a single query."""
    from sqlalchemy import func
    if not task_ids:
        return {}
    rows = (
        db.query(Attachment.task_id, func.count(Attachment.id))
        .filter(Attachment.task_id.in_(task_ids))
        .group_by(Attachment.task_id)
        .all()
    )
    return {task_id: count for task_id, count in rows}


def _attachment_count(db: Session, task_id: str) -> int:
    from sqlalchemy import func
    return db.query(func.count(Attachment.id)).filter(Attachment.task_id == task_id).scalar() or 0


def _with_profile_relations(query):
    """Eager-load the relationships _profile_to_dict() touches (AP-433).
    Without this, serializing N profiles fires 3N extra SELECTs — roles,
    extra_permissions (+ its nested .permission), project_memberships —
    the N+1 behind list_profiles/list_project_members' multi-second loads."""
    return query.options(
        selectinload(Profile.roles),
        selectinload(Profile.extra_permissions).selectinload(ProfilePermission.permission),
        selectinload(Profile.project_memberships),
    )


def _batch_epic_task_counts(db: Session, epic_ids: list[str]) -> dict[str, int]:
    """Return {epic_id: count} for all given epic IDs in a single query."""
    from sqlalchemy import func
    if not epic_ids:
        return {}
    rows = (
        db.query(Task.epic_id, func.count(Task.id))
        .filter(Task.epic_id.in_(epic_ids))
        .group_by(Task.epic_id)
        .all()
    )
    return {epic_id: count for epic_id, count in rows}


def _project_to_dict(p: Project, task_count: Optional[int] = None) -> dict:
    return {
        "id": p.id,
        "key_prefix": p.key_prefix or "PROJ",
        "name": p.name,
        "description": p.description,
        "repo_path": p.repo_path or "",
        "repo_url": getattr(p, "repo_url", None) or "",
        # AP-197: how the daemon provisions the working copy ("" = inferred).
        "workspace_kind": getattr(p, "workspace_kind", None) or "",
        "conventions_md": p.conventions_md or "",
        # ADR 009 / AP-136: run-crystallization work-signal mode ("" = default).
        "work_signal": getattr(p, "work_signal", None) or "",
        # AP-155: project-level sandbox override ("" = inherit from agent).
        "sandbox_mode": getattr(p, "sandbox_mode", None) or "",
        # AP-308: per-run environment isolation ("" = auto). Override cmds/url
        # are advanced knobs; surfaced so the settings form round-trips them.
        "env_isolation": getattr(p, "env_isolation", None) or "",
        "env_setup_cmd": getattr(p, "env_setup_cmd", None) or "",
        "env_teardown_cmd": getattr(p, "env_teardown_cmd", None) or "",
        "env_db_admin_url": getattr(p, "env_db_admin_url", None) or "",
        # AP-158: column-exit gates on/off for this project.
        "gates_enabled": bool(getattr(p, "gates_enabled", False)),
        # AP-184: when on, ANY comment wakes the assigned agent (legacy). Off
        # (default) = only @mention wakes; a plain comment is recorded as context.
        "wake_on_comment": bool(getattr(p, "wake_on_comment", False)),
        # Workflow driver opt-in + the restricted customer override (role->agent
        # mapping only; the flow itself is system config, view-only).
        "workflow_enabled": bool(getattr(p, "workflow_enabled", False)),
        "workflow_roles_json": getattr(p, "workflow_roles_json", None) or "",
        # AP-297: TTL (seconds) for cached pre-run checks. null = default (600);
        # 0 = never expire by age (re-run only when the environment changes).
        "ready_checks_ttl_seconds": getattr(p, "ready_checks_ttl_seconds", None),
        # Where this project deploys (kind picks the adapter). The opaque
        # config blob + credential status are fetched separately via
        # get_project_deploy_settings — not inlined here to keep the token
        # out of the general project serialization.
        "deploy_target_kind": getattr(p, "deploy_target_kind", None) or "railway",
        "created_at": p.created_at.isoformat(),
        "task_count": len(p.tasks) if task_count is None else task_count,
        "members": [m.profile.name for m in p.members],
    }


def _activity_to_dict(a: Activity) -> dict:
    import json
    diff = None
    if a.diff:
        try:
            diff = json.loads(a.diff)
        except Exception:
            diff = a.diff
    return {
        "id": a.id,
        "task_id": a.task_id,
        "actor": a.actor,
        "action": a.action,
        "detail": a.detail,
        "diff": diff,
        "created_at": a.created_at.isoformat(),
    }


def _profile_to_dict(p: Profile) -> dict:
    extra = [pp.permission.codename for pp in p.extra_permissions]
    roles = p.role_names
    account_type = p.account_type
    # Legacy `kind` (still read by some daemon/MCP consumers) — derive from the
    # stored account_type so the old triplet keeps working during transition.
    kind = {"human": "user", "agentira_agent": "managed_agent",
            "external_agent": "service_account"}.get(account_type, "user")
    return {
        "id": p.id,
        "org_id": p.org_id,
        "name": p.name,
        "display_name": p.display_name or p.name,
        "account_type": account_type,
        "roles": roles,
        # Back-compat: a single `role` (first role) for callers not yet on the
        # `roles` list (frontend badge, JWT minting, api-key fallback).
        "role": roles[0] if roles else None,
        "kind": kind,
        "email": p.email,
        "must_change_password": bool(getattr(p, "must_change_password", False)),
        "avatar_url": p.avatar_url,
        "webhook_url": p.webhook_url,
        "extra_permissions": extra,
        "projects": [pm.project_id for pm in p.project_memberships],
        "runtime_id": p.runtime_id,
        # AP-155: agent's default containment posture ("" = workspace default).
        "sandbox_mode": getattr(p, "sandbox_mode", None) or "",
        # AP-302: personal git token — presence + validity only, never value.
        "has_git_token": bool(getattr(p, "git_token", None)),
        "git_token_valid": getattr(p, "git_token_valid", None),
        "git_token_checked_at": (
            p.git_token_checked_at.isoformat()
            if getattr(p, "git_token_checked_at", None) else None
        ),
        "created_at": p.created_at.isoformat(),
    }


def _get_status_id(db: Session, status_name: str) -> str:
    """Resolve a status name to its ID. Raises ValueError if not found."""
    s = db.query(Status).filter(Status.name == status_name).first()
    if not s:
        raise ValueError(f"Status '{status_name}' not found")
    return s.id


def _get_role_id(db: Session, role_name: str) -> str:
    """Resolve a role name to its ID. Raises ValueError if not found."""
    r = db.query(Role).filter(Role.name == role_name).first()
    if not r:
        raise ValueError(f"Role '{role_name}' not found")
    return r.id


def _resolve_roles(db: Session, names: list[str]) -> list[Role]:
    """Resolve role names to Role objects (for the profile_roles M2M).
    Raises ValueError on any unknown name; de-duplicates while preserving order."""
    seen: set[str] = set()
    out: list[Role] = []
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        r = db.query(Role).filter(Role.name == n).first()
        if not r:
            raise ValueError(f"Role '{n}' not found")
        out.append(r)
    return out


def _get_profile_by_name(db: Session, name: str) -> Profile | None:
    return db.query(Profile).filter(Profile.name == name).first()


def _log_activity(
    db: Session,
    actor: str,
    action: str,
    detail: str,
    project_id: str | None = None,
    task_id: str | None = None,
    notify_users: list[str] = [],
    diff: str | None = None,
) -> Activity:
    """Centralized audit logging and notification dispatch."""
    activity = Activity(
        project_id=project_id,
        task_id=task_id,
        actor=actor,
        action=action,
        detail=detail,
        diff=diff,
    )
    db.add(activity)
    
    # Notifications
    for profile_name in notify_users:
        prof = _get_profile_by_name(db, profile_name)
        if not prof:
            continue
            
        n = Notification(
            profile_id=prof.id,
            type=action,
            title=f"{action}: {detail[:100]}",
            link=f"/tasks/{task_id}" if task_id else f"/projects/{project_id}"
        )
        db.add(n)
        # Broker notification happens after commit (caller's job or we add hook)
    
    return activity


def list_notifications(profile_id: str, unread_only: bool = True,
                       limit: int = 100) -> list[dict]:
    with _session() as db:
        q = db.query(Notification).filter(Notification.profile_id == profile_id)
        if unread_only:
            q = q.filter(Notification.read == False)
        notifs = q.order_by(Notification.created_at.desc()).limit(limit).all()
        return [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "link": n.link,
                "read": n.read,
                "created_at": n.created_at.isoformat()
            }
            for n in notifs
        ]


def mark_notification_read(notification_id: str, actor_profile_id: str | None = None) -> bool:
    with _session() as db:
        n = db.get(Notification, notification_id)
        if not n:
            return False
        if actor_profile_id and n.profile_id != actor_profile_id:
            return False
        n.read = True
        db.commit()
        return True


# ── Project operations ──────────────────────────────────────────────────

def _derive_prefix(name: str) -> str:
    """Derive a short uppercase prefix from a project name."""
    import re
    words = re.findall(r'[A-Za-z]+', name)
    if not words:
        return "PROJ"
    if len(words) == 1:
        w = words[0].upper()
        consonants = re.sub(r'[AEIOU]', '', w)
        return (consonants[:4] if len(consonants) >= 3 else w[:4]).ljust(2, 'X')
    return ''.join(w[0].upper() for w in words[:5])


_KICKOFF_TASK_TITLE = "Plan this project"
# AP-152 / prompts-as-config: the task body is intentionally empty.
# The Conductor's UI-editable system prompt is the source of truth for
# how it handles a kickoff task. Body content belongs on the agent's
# persona, not in service code.


def create_project(name: str, description: str = "", actor: str = "system",
                   *, initial_tasks: list[dict] | None = None,
                   members: list[str] | None = None,
                   seed_defaults: bool = False) -> dict:
    """Create a project.

    Two modes:
    - **Legacy (initial_tasks=None, members=None)**: auto-seed — the
      Conductor is added as a member and one "Plan this project" task
      (empty body) is created. Same behavior the MCP `create_project`
      tool and pre-AP-153 callers rely on.
    - **Wizard (AP-153)**: caller supplies `initial_tasks` (each
      `{title, description, assignee?, priority?}`) and `members`
      (list of profile names). Auto-seed is skipped — the wizard owns
      both the task bodies *and* membership choices. Empty lists are
      legitimate: "I want a project with no preset tasks / agents."
    """
    with _session() as db:
        prefix = _derive_prefix(name)
        # Deduplicate prefix
        existing = {r[0] for r in db.query(Project.key_prefix).all() if r[0]}
        base = prefix
        i = 2
        while prefix in existing:
            prefix = f"{base}{i}"
            i += 1
        project = Project(name=name, description=description, key_prefix=prefix)
        db.add(project)
        db.flush()

        # Auto-add creator as a project member
        if actor and actor != "system":
            creator = _get_profile_by_name(db, actor)
            if creator:
                db.add(ProjectMember(project_id=project.id, profile_id=creator.id))

        _log_activity(db, actor, "project.create", f"Created project: {name}", project_id=project.id)
        db.commit()
        db.refresh(project)
        project_id = project.id
        result = _project_to_dict(project)

    use_wizard = initial_tasks is not None or members is not None
    if use_wizard:
        # AP-153: the wizard owns membership + initial tasks. Bodies come
        # from the user via the UI, not from a code constant.
        for profile_name in (members or []):
            try:
                add_project_member(project_id, profile_name, actor=actor)
            except Exception as exc:  # noqa: BLE001
                logger.warning("wizard add_member failed project=%s name=%s: %s",
                               project_id, profile_name, exc)
        for spec in (initial_tasks or []):
            title = (spec.get("title") or "").strip()
            if not title:
                continue
            try:
                create_task(
                    project_id=project_id,
                    title=title,
                    description=spec.get("description", ""),
                    status=spec.get("status", "todo"),
                    priority=spec.get("priority", "medium"),
                    assignee=spec.get("assignee", "") or "",
                    actor=actor,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("wizard initial-task create failed project=%s: %s",
                               project_id, exc)
    else:
        # Legacy auto-seed — Conductor + empty "Plan this project" task.
        # Conductor is the workspace orchestrator
        # (backend/forge/conductor.py). Best-effort: if the Conductor isn't
        # seedable (missing 'bot' role on a fresh install) the project is
        # still returned.
        try:
            _seed_project_kickoff(project_id=project_id, actor=actor)
        except Exception as exc:  # noqa: BLE001 — project must still be created
            logger.warning("project kickoff seeding failed project=%s: %s",
                           project_id, exc)

    if seed_defaults:
        # Seed the default "professionalization" backlog (epics + tasks) the
        # user can run with the Conductor. Best-effort: failure must not sink
        # the project create.
        try:
            from backend import default_tasks
            default_tasks.seed_default_tasks(project_id, actor=actor)
        except Exception as exc:  # noqa: BLE001
            logger.warning("default-tasks seeding failed project=%s: %s",
                           project_id, exc)

    return result


def _seed_project_kickoff(*, project_id: str, actor: str) -> None:
    """Add the Conductor as a project member and create the kickoff task."""
    from backend.forge.conductor import get_or_create_conductor, CONDUCTOR_NAME
    cond = get_or_create_conductor()
    if not isinstance(cond, dict) or cond.get("error"):
        logger.info("Conductor not available — skipping kickoff: %s", cond)
        return

    # Add Conductor as a project member (idempotent — duplicate inserts
    # just fail benignly; we catch).
    with _session() as db:
        cond_prof = _get_profile_by_name(db, CONDUCTOR_NAME)
        if not cond_prof:
            return
        already = (db.query(ProjectMember)
                     .filter_by(project_id=project_id, profile_id=cond_prof.id)
                     .first())
        if not already:
            db.add(ProjectMember(project_id=project_id, profile_id=cond_prof.id))
            db.commit()

    # Create the kickoff task assigned to the Conductor. status=todo so it
    # shows up immediately, not buried in backlog.
    try:
        create_task(
            project_id=project_id,
            title=_KICKOFF_TASK_TITLE,
            description="",
            status="todo",
            priority="high",
            assignee=CONDUCTOR_NAME,
            actor=actor,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("kickoff task create failed project=%s: %s",
                       project_id, exc)


def list_projects(actor: str = "system") -> list[dict]:
    """List projects, scoped by visibility rules.

    - Admin / 'project.view_all': Sees all projects.
    - Others: Sees only projects they are a member of.
    """
    from backend.repos import projects as projects_repo
    from sqlalchemy.orm import selectinload

    member_eager = selectinload(Project.members).selectinload(ProjectMember.profile)

    with _session() as db:
        if has_permission(db, actor, "project.view_all"):
            projects = (
                db.query(Project)
                .options(member_eager)
                .order_by(Project.created_at.desc())
                .all()
            )
        else:
            profile = _get_profile_by_name(db, actor)
            if not profile:
                return []
            projects = (
                db.query(Project)
                .join(ProjectMember)
                .filter(ProjectMember.profile_id == profile.id)
                .options(member_eager)
                .order_by(Project.created_at.desc())
                .all()
            )
        counts = projects_repo.task_counts_by_project(db, [p.id for p in projects])
        return [_project_to_dict(p, task_count=counts.get(p.id, 0)) for p in projects]


def get_project(project_id: str, actor: str = "system") -> dict | None:
    with _session() as db:
        require_project_access(db, actor, project_id, "read")
        p = db.get(Project, project_id)
        return _project_to_dict(p) if p else None


def update_project(project_id: str, name: Optional[str] = None, description: Optional[str] = None,
                   repo_path: Optional[str] = None, conventions_md: Optional[str] = None,
                   work_signal: Optional[str] = None,
                   sandbox_mode: Optional[str] = None,
                   env_isolation: Optional[str] = None,
                   env_setup_cmd: Optional[str] = None,
                   env_teardown_cmd: Optional[str] = None,
                   env_db_admin_url: Optional[str] = None,
                   gates_enabled: Optional[bool] = None,
                   wake_on_comment: Optional[bool] = None,
                   repo_url: Optional[str] = None,
                   workspace_kind: Optional[str] = None,
                   workflow_enabled: Optional[bool] = None,
                   workflow_roles_json: Optional[str] = None,
                   ready_checks_ttl_seconds: Optional[int] = None,
                   actor: str = "system") -> dict:
    with _session() as db:
        require_project_access(db, actor, project_id, "write")
        p = db.get(Project, project_id)
        if not p:
            raise ValueError(f"Project {project_id} not found")
        if name is not None:
            p.name = name
        if description is not None:
            p.description = description
        if repo_path is not None:
            p.repo_path = repo_path
        if repo_url is not None:
            # AP-197: empty string clears the remote.
            p.repo_url = repo_url.strip() or None
        if workspace_kind is not None:
            # AP-197: empty string re-enables inference. Validate against the
            # known kinds; ignore junk so a bad value can't wedge dispatch.
            wk = workspace_kind.strip().lower() or None
            if wk in (None, "git", "sandbox", "local_folder"):
                p.workspace_kind = wk
        if conventions_md is not None:
            p.conventions_md = conventions_md
        if work_signal is not None:
            # ADR 009: validate against the known modes; ignore junk.
            from backend.forge.turns import WORK_SIGNAL_MODES
            if work_signal in WORK_SIGNAL_MODES:
                p.work_signal = work_signal
        if sandbox_mode is not None:
            # AP-155: empty string clears the override (re-inherit from agent).
            from backend.sandbox import is_valid_mode
            normalized = sandbox_mode.strip() or None
            if is_valid_mode(normalized):
                p.sandbox_mode = normalized
        if env_isolation is not None:
            # AP-308: empty string re-enables auto. Validate against the known
            # modes; ignore junk so a bad value can't wedge dispatch.
            mode = env_isolation.strip().lower() or None
            if mode in (None, "auto", "hermetic", "per_run_db", "per_run_compose"):
                # "auto" is stored as NULL — same as unset.
                p.env_isolation = None if mode in (None, "auto") else mode
        if env_setup_cmd is not None:
            p.env_setup_cmd = env_setup_cmd.strip() or None
        if env_teardown_cmd is not None:
            p.env_teardown_cmd = env_teardown_cmd.strip() or None
        if env_db_admin_url is not None:
            p.env_db_admin_url = env_db_admin_url.strip() or None
        if gates_enabled is not None:
            p.gates_enabled = bool(gates_enabled)
        if wake_on_comment is not None:
            p.wake_on_comment = bool(wake_on_comment)
        if workflow_enabled is not None:
            p.workflow_enabled = bool(workflow_enabled)
        if workflow_roles_json is not None:
            # The restricted customer surface: role->agent mapping overrides
            # only. Empty string clears. Validate via the workflow schema —
            # reject junk so a bad override can't be persisted.
            raw = workflow_roles_json.strip() or None
            if raw is not None:
                import json as _json
                from backend.forge.workflow import RoleSpec
                try:
                    data = _json.loads(raw)
                    if not isinstance(data, dict):
                        raise ValueError("must be a JSON object")
                    for role_name, spec in data.items():
                        RoleSpec(**spec)  # validation only
                except Exception as exc:
                    raise ValueError(f"invalid workflow_roles_json: {exc}")
            p.workflow_roles_json = raw
        if ready_checks_ttl_seconds is not None:
            # AP-297: three states. <0 resets to the default (NULL → 600s);
            # 0 = never expire by age; >0 = custom seconds. None = no change
            # (function convention), so a negative sentinel reaches "default".
            ttl = int(ready_checks_ttl_seconds)
            p.ready_checks_ttl_seconds = None if ttl < 0 else ttl
        db.commit()
        db.refresh(p)
        return _project_to_dict(p)


def set_workflow_prompt_override(project_id: str, *, slug: str,
                                 text: Optional[str]) -> dict:
    """Persist (or clear) a per-project prompt-text override on
    Project.workflow_prompts_json. Empty / None text removes the slug's
    override; the driver falls back to the system template.

    slug validity is checked against the union of role-prompt slugs and the
    bounce/rejection policy prompts — no dumping ground; unknown slugs 400.
    """
    import json as _json
    from backend.forge import workflow as _workflow
    with _session() as db:
        p = db.get(Project, project_id)
        if not p:
            raise KeyError(f"Project {project_id} not found")
        flow = _workflow.effective_workflow(p)
        allowed: set[str] = {"gate_bounce",
                             getattr(flow.rejection, "prompt", "")
                             or "rejection_handback"}
        for role_name, role in flow.roles.items():
            allowed.add(role.prompt if role.prompt else role_name)
        allowed.discard("")
        if slug not in allowed:
            raise ValueError(
                f"unknown prompt slug '{slug}' (known: {sorted(allowed)})")
        current: dict = {}
        raw = getattr(p, "workflow_prompts_json", None)
        if raw:
            try:
                loaded = _json.loads(raw)
                if isinstance(loaded, dict):
                    current = {k: v for k, v in loaded.items()
                               if isinstance(k, str) and isinstance(v, str)}
            except ValueError:
                current = {}
        if text is None or not text.strip():
            current.pop(slug, None)
        else:
            current[slug] = text
        p.workflow_prompts_json = _json.dumps(current) if current else None
        db.commit()
        return {"slug": slug, "is_override": slug in current,
                "override": current.get(slug, "")}


# Deploy settings are handled by DeploymentManager; this gateway owns the
# session/commit and funnels REST/MCP calls to it.
_deploy_manager = DeploymentManager()


def get_project_deploy_settings(project_id: str) -> dict:
    with _session() as db:
        return _deploy_manager.get_settings(db, project_id)


def set_project_deploy_target(project_id: str, *, kind: str,
                              config: dict | None = None) -> dict:
    with _session() as db:
        result = _deploy_manager.set_target(db, project_id, kind=kind, config=config)
        db.commit()
        return result


def set_deploy_credential(project_id: str, *, kind: str, token: str) -> dict:
    with _session() as db:
        result = _deploy_manager.set_credential(db, project_id, kind=kind, token=token)
        db.commit()
        return result


def verify_deploy_key(project_id: str, *, provider: str, api_key: str) -> dict:
    """Probe-only: the wizard is still holding the key, so nothing is stored and
    there is nothing to commit."""
    with _session() as db:
        return _deploy_manager.verify_key(
            db, project_id, kind=provider, token=api_key)


# Deploy *flow* (provider connection + deployment lifecycle) — same gateway
# shape: this owns the session/commit and delegates to the DeployFlow handler.
_deploy_flow = DeployFlow()


def get_deploy_connection(project_id: str) -> dict:
    with _session() as db:
        return _deploy_flow.get_connection(db, project_id)


def connect_deploy_provider(project_id: str, *, provider: str, api_key: str,
                            repo: str, service_id: str) -> dict:
    with _session() as db:
        result = _deploy_flow.connect(
            db, project_id, provider=provider, api_key=api_key,
            repo=repo, service_id=service_id)
        db.commit()
        return result


def reverify_deploy_provider(project_id: str) -> dict:
    with _session() as db:
        result = _deploy_flow.reverify(db, project_id)
        db.commit()
        return result


def disconnect_deploy_provider(project_id: str) -> None:
    with _session() as db:
        _deploy_flow.disconnect(db, project_id)
        db.commit()


def get_deploy_repo_access(project_id: str, *, provider: str) -> dict:
    with _session() as db:
        return _deploy_flow.repo_access(db, project_id, provider)


def list_deployments(project_id: str) -> dict:
    with _session() as db:
        return _deploy_flow.list_deployments(db, project_id)


def create_deployment(project_id: str, *, branch: str) -> dict:
    with _session() as db:
        result = _deploy_flow.create_deployment(db, project_id, branch=branch)
        db.commit()
        return result


def redeploy_deployment(project_id: str, deployment_id: str) -> dict:
    with _session() as db:
        result = _deploy_flow.redeploy(db, project_id, deployment_id)
        db.commit()
        return result


def stop_deployment(project_id: str, deployment_id: str) -> None:
    with _session() as db:
        _deploy_flow.stop(db, project_id, deployment_id)
        db.commit()


def get_deployment_logs(project_id: str, deployment_id: str, *, cursor: int = 0) -> dict:
    with _session() as db:
        return _deploy_flow.get_logs(db, project_id, deployment_id, cursor=cursor)


def delete_project(project_id: str, actor: str = "system") -> bool:
    """Cascade-delete a project and everything it owns: tasks, epics, members,
    activities, attachments (rows + on-disk files), forge runs, and chats.

    ORM cascade handles the core children (tasks/epics/members/activities/
    attachment rows). Forge runs/chats and the default-project pointers carry
    no cascade, so they're cleared first via repos — otherwise the delete
    FK-violates on `forge_runs`."""
    from backend.repos import projects as projects_repo
    from backend.forge.repos import project_purge
    from backend import attachments
    with _session() as db:
        require_project_access(db, actor, project_id, "write")
        p = db.get(Project, project_id)
        if not p:
            return False
        task_ids = [t.id for t in p.tasks]
        attachments.purge_project_files(project_id, task_ids)
        project_purge.purge_project_data(db, project_id=project_id,
                                         task_ids=task_ids)
        projects_repo.delete_project_repos(db, project_id)
        projects_repo.clear_default_project_pointers(db, project_id)
        db.delete(p)
        db.commit()
        return True


def add_project_member(project_id: str, profile_name: str, actor: str = "system") -> dict:
    """Add a user to a project."""
    with _session() as db:
        require_project_access(db, actor, project_id, "membership_admin")
        p = db.get(Project, project_id)
        if not p:
            raise ValueError(f"Project {project_id} not found")

        prof = _get_profile_by_name(db, profile_name)
        if not prof:
            raise ValueError(f"Profile {profile_name} not found")

        existing = db.query(ProjectMember).filter_by(project_id=p.id, profile_id=prof.id).first()
        if not existing:
            db.add(ProjectMember(project_id=p.id, profile_id=prof.id))
            _log_activity(
                db, actor, "project.member.add",
                f"Added {profile_name} to project {p.name}",
                project_id=p.id,
                notify_users=[profile_name]
            )
            db.commit()
            broker.notify(prof.id)
            agent_notifier.dispatch_project(db, "project.member.add", _project_to_dict(p), actor)

        return _project_to_dict(p)


def list_project_members(project_id: str, actor: str = "system") -> list[dict]:
    """Return all members of a project as profile dicts."""
    with _session() as db:
        require_project_access(db, actor, project_id, "read")
        p = db.get(Project, project_id)
        if not p:
            return []
        members = (
            db.query(ProjectMember)
            .filter_by(project_id=p.id)
            .options(
                selectinload(ProjectMember.profile).selectinload(Profile.roles),
                selectinload(ProjectMember.profile).selectinload(Profile.extra_permissions)
                    .selectinload(ProfilePermission.permission),
                selectinload(ProjectMember.profile).selectinload(Profile.project_memberships),
            )
            .all()
        )
        return [_profile_to_dict(pm.profile) for pm in members]


def remove_project_member(
    project_id: str,
    profile_name: str,
    actor: str = "system",
) -> bool:
    """Remove a user from a project and clear their task assignments."""
    with _session() as db:
        require_project_access(db, actor, project_id, "membership_admin")
        p = db.get(Project, project_id)
        prof = _get_profile_by_name(db, profile_name)
        if not p or not prof:
            return False

        pm = db.query(ProjectMember).filter_by(project_id=p.id, profile_id=prof.id).first()
        if not pm:
            return False
        
        # Clear assignments for this user in this project. A direct field
        # write outside TaskService, but audited: it's a legitimate
        # cascade cleanup and it logs an activity row per task below —
        # allow_task_write() makes that an explicit, visible exception
        # rather than a silent bypass.
        from backend.models import allow_task_write
        tasks = db.query(Task).filter_by(project_id=p.id, assignee=profile_name).all()
        for t in tasks:
            with allow_task_write():
                t.assignee = ""
            _log_activity(
                db, 
                actor="system", 
                action="task.unassign", 
                detail=f"User {profile_name} removed from project; assignment cleared.",
                project_id=p.id,
                task_id=t.id
            )

        db.delete(pm)
        db.commit()
        return True


# ── Epic operations ─────────────────────────────────────────────────────

def _epic_to_dict(e: Epic, task_count: Optional[int] = None) -> dict:
    return {
        "id": e.id,
        "project_id": e.project_id,
        "title": e.title,
        "description": e.description,
        "status": e.status,
        "assignee": e.assignee,
        "creator": e.creator,
        "color": e.color,
        "task_count": len(e.tasks) if task_count is None else task_count,
        "created_at": e.created_at.isoformat(),
    }

def create_epic(project_id: str, title: str, description: str = "", color: str = "#7c4dff", actor: str = "system") -> dict:
    with _session() as db:
        require_project_access(db, actor, project_id, "write")
        project = db.get(Project, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        epic = Epic(
            project_id=project_id,
            title=title,
            description=description,
            color=color,
            creator=actor,
        )
        db.add(epic)
        db.flush()
        _log_activity(db, actor, "epic.create", f"Created epic: {title}", project_id=project_id)
        db.commit()
        db.refresh(epic)
        return _epic_to_dict(epic)

def list_epics(project_id: Optional[str] = None, actor: str = "system") -> list[dict]:
    with _session() as db:
        q = db.query(Epic)
        project_ids = project_ids_for_actor(db, actor)
        if project_ids is not None:
            q = q.filter(Epic.project_id.in_(project_ids))

        if project_id:
            q = q.filter(Epic.project_id == project_id)

        epics = q.order_by(Epic.created_at.desc()).all()
        counts = _batch_epic_task_counts(db, [e.id for e in epics])
        return [_epic_to_dict(e, task_count=counts.get(e.id, 0)) for e in epics]

def get_epic(epic_id: str, actor: str = "system") -> dict | None:
    """Single-epic fetch — returns the dict or None if not found."""
    with _session() as db:
        epic = db.get(Epic, epic_id)
        if epic:
            require_project_access(db, actor, epic.project_id, "read")
        return _epic_to_dict(epic) if epic else None


def list_epic_tasks(epic_id: str, actor: str = "system") -> list[dict]:
    """All tasks linked to this epic, newest first."""
    with _session() as db:
        epic = db.get(Epic, epic_id)
        if not epic:
            return []
        require_project_access(db, actor, epic.project_id, "read")
        tasks = (db.query(Task)
                 .filter(Task.epic_id == epic_id)
                 .order_by(Task.updated_at.desc())
                 .all())
        return [_task_to_dict(t) for t in tasks]


def update_epic(epic_id: str, title: Optional[str] = None, description: Optional[str] = None, color: Optional[str] = None, actor: str = "system") -> dict:
    with _session() as db:
        epic = db.get(Epic, epic_id)
        if not epic:
            raise ValueError(f"Epic {epic_id} not found")
        require_project_access(db, actor, epic.project_id, "write")
        changes = []
        if title is not None and title != epic.title:
            epic.title = title
            changes.append(f"title -> {title}")
        if description is not None and description != epic.description:
            epic.description = description
            changes.append("description updated")
        if color is not None and color != epic.color:
            epic.color = color
            changes.append("color updated")
        
        if changes:
            _log_activity(db, actor, "epic.update", "; ".join(changes), project_id=epic.project_id)
            db.commit()
            db.refresh(epic)
        return _epic_to_dict(epic)

def delete_epic(epic_id: str, actor: str = "system") -> bool:
    with _session() as db:
        epic = db.get(Epic, epic_id)
        if not epic:
            return False
        require_project_access(db, actor, epic.project_id, "write")
        # Unlink tasks before deleting
        for t in epic.tasks:
            t.epic_id = None
        db.delete(epic)
        db.commit()
        return True


# ── Task operations ─────────────────────────────────────────────────────

def create_task(
    project_id: str,
    title: str,
    description: str = "",
    status: str = "backlog",
    priority: str = "medium",
    assignee: str = "",
    tags: list[str] | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    dod_items: Optional[list[dict]] = None,
    epic_id: str | None = None,
    actor: str = "system",
    type: str = "task",
    parent_id: str | None = None,
    milestone_id: str | None = None,
) -> dict:
    """Create a task. Delegates to the typed task domain (backend.tasks)."""
    from backend import tasks
    return tasks.resolve(type).create(
        project_id, title, description, status, priority, assignee, tags,
        start_date, due_date, dod_items, epic_id, actor,
        parent_id=parent_id, milestone_id=milestone_id,
    )


# ── Task graph (AP-496) ─────────────────────────────────────────────────
# Thin delegations so REST/MCP callers keep talking to `services` while the
# rules live in backend.task_graph.

def list_subtasks(task_id: str, actor: str = "system") -> list[dict]:
    from backend import task_graph
    return task_graph.list_subtasks(task_id, actor=actor)


def list_dependencies(project_id: str, actor: str = "system") -> list[dict]:
    from backend import task_graph
    return task_graph.list_dependencies(project_id, actor=actor)


def add_dependency(project_id: str, task_id: str, depends_on_id: str,
                   actor: str = "system") -> dict:
    from backend import task_graph
    return task_graph.add_dependency(project_id, task_id, depends_on_id, actor=actor)


def remove_dependency(project_id: str, dependency_id: str,
                      actor: str = "system") -> bool:
    from backend import task_graph
    return task_graph.remove_dependency(project_id, dependency_id, actor=actor)


def list_milestones(project_id: str, actor: str = "system") -> list[dict]:
    from backend import task_graph
    return task_graph.list_milestones(project_id, actor=actor)


def create_milestone(project_id: str, title: str, description: str = "",
                     due_date: str | None = None, color: str = "#2ecc71",
                     actor: str = "system") -> dict:
    from backend import task_graph
    return task_graph.create_milestone(
        project_id, title=title, description=description, due_date=due_date,
        color=color, actor=actor)


def update_milestone(project_id: str, milestone_id: str, title: str | None = None,
                     description: str | None = None, due_date: str | None = None,
                     status: str | None = None, color: str | None = None,
                     actor: str = "system") -> dict:
    from backend import task_graph
    return task_graph.update_milestone(
        project_id, milestone_id, title=title, description=description,
        due_date=due_date, status=status, color=color, actor=actor)


def delete_milestone(project_id: str, milestone_id: str,
                     actor: str = "system") -> bool:
    from backend import task_graph
    return task_graph.delete_milestone(project_id, milestone_id, actor=actor)


def list_tasks(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    priority: Optional[str] = None,
    actor: str = "system",
) -> list[dict]:
    """List tasks scoped by visibility. Delegates to backend.tasks."""
    from backend import tasks
    return tasks.TaskService().list(project_id, status, assignee, priority, actor)


def get_task(task_id: str, actor: str = "system") -> dict | None:
    from backend import tasks
    return tasks.TaskService().get(task_id, actor)


def update_task(
    task_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    assignee: Optional[str] = None,
    tags: Optional[list[str]] = None,
    start_date: Optional[str] = None,
    due_date: Optional[str] = None,
    dod_items: Optional[list[dict]] = None,
    branch: Optional[str] = None,
    pr_url: Optional[str] = None,
    epic_id: Optional[str] = None,
    repos: Optional[list[str]] = None,
    parent_id: Optional[str] = None,
    milestone_id: Optional[str] = None,
    actor: str = "system",
) -> dict:
    """Update a task. Delegates to backend.tasks."""
    from backend import tasks
    return tasks.TaskService().update(
        task_id, title, description, priority, assignee, tags, start_date,
        due_date, dod_items, branch, pr_url, epic_id, repos,
        parent_id=parent_id, milestone_id=milestone_id, actor=actor,
    )


def move_task(task_id: str, new_status: str, actor: str = "system",
              skip_gates: bool = False, record_transition: bool = True) -> dict:
    from backend import tasks
    return tasks.TaskService().move(task_id, new_status, actor, skip_gates,
                                    record_transition=record_transition)


def delete_task(task_id: str, actor: str = "system") -> bool:
    from backend import tasks
    return tasks.TaskService().delete(task_id, actor)


# ── Activity / comments ─────────────────────────────────────────────────

def add_comment(task_id: str, comment: str, actor: str = "system") -> dict:
    with _session() as db:
        task = _resolve_task(db, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        require_project_access(db, actor, task.project_id, "write")
        task_id = task.id
        # Capture while the session is open (task detaches after the block).
        _wake_on_comment = bool(getattr(task.project, "wake_on_comment", False))

        act = _log_activity(
            db, actor, "commented", comment,
            project_id=task.project_id, task_id=task_id,
            notify_users=[task.assignee] if task.assignee and task.assignee != actor else []
        )

        db.commit()
        if task.assignee and task.assignee != actor:
            target_prof = _get_profile_by_name(db, task.assignee)
            if target_prof:
                broker.notify(target_prof.id)
        agent_notifier.dispatch(db, "task.commented", _task_to_dict(task), actor)

        db.refresh(act)
        result = _activity_to_dict(act)

    # Deliver the comment to the assigned agent's task chat. A plain comment is
    # RECORDED as context (no run); only an @mention of the agent — or the
    # project's wake_on_comment toggle — wakes it immediately (AP-184). Skip if
    # the actor IS the assignee (an agent's own comment must not re-dispatch).
    if task.assignee and task.assignee != actor:
        try:
            _deliver_comment_to_agent(
                task_id=task_id, assignee_name=task.assignee,
                actor=actor, comment=comment,
                wake_on_comment=_wake_on_comment,
            )
        except Exception as exc:  # noqa: BLE001 — comment must succeed regardless
            logger.warning("comment-delivery failed task=%s: %s", task_id, exc)

    return result


def _comment_mentions_agent(comment: str, names: list[str]) -> bool:
    """True if the comment @mentions this agent — by any of its names/handles
    (spaces stripped) or the generic ``@agent``."""
    c = (comment or "").lower()
    c_nospace = c.replace(" ", "")
    if "@agent" in c_nospace:
        return True
    for n in names:
        if not n:
            continue
        nl = n.lower()
        if f"@{nl}" in c or f"@{nl.replace(' ', '')}" in c_nospace:
            return True
    return False


def _deliver_comment_to_agent(*, task_id: str, assignee_name: str,
                              actor: str, comment: str,
                              wake_on_comment: bool) -> None:
    """Comment -> assigned agent's task chat (AP-184).

    @mention (or the wake_on_comment toggle) → dispatch now via
    send_runtime_message (auto-routes per run state). Otherwise → record the
    comment into the task chat as context, no dispatch; the agent reads it when
    it next starts work. Skips silently for non-agent assignees (humans) or
    agents without a runtime (purely HTTP-executor agents).
    """
    from backend.forge.models import Agent as ForgeAgent
    from backend.forge import services as forge_services
    from backend.forge import runs as forge_runs
    with _session() as db:
        prof = _get_profile_by_name(db, assignee_name)
        if not prof:
            return
        agent = (db.query(ForgeAgent)
                   .filter(ForgeAgent.profile_id == prof.id)
                   .first())
        if not agent or not agent.runtime_id:
            return
        agent_id = agent.id
        names = [agent.name, agent.runtime_agent_name, prof.name, assignee_name]

    # Strictly one run per (agent, task): a comment never opens a second run.
    # If the task's single run is parked (needs_input/blocked) or paused, a
    # comment must NOT revive it (that made a comment look like it drove a "run
    # with work"). So we record it as context — visible to the agent on its
    # next turn — instead of dispatching. A wake into a non-parked run reuses
    # the single run as the next turn.
    woke = wake_on_comment or _comment_mentions_agent(comment, names)
    if woke and not forge_runs.latest_task_run_is_parked(agent_id, task_id):
        forge_services.send_runtime_message(
            agent_id,
            content=f"[Comment from {actor}] {comment}",
            scope_key=f"task:{task_id}",
        )
    else:
        forge_services.record_task_comment(
            agent_id=agent_id, task_id=task_id, actor=actor, content=comment,
        )


def get_activity(
    task_id: str,
    limit: int = 100,
    offset: int = 0,
    actor: str = "system",
) -> list[dict]:
    with _session() as db:
        task = _resolve_task(db, task_id)
        if not task:
            return []
        require_project_access(db, actor, task.project_id, "read")
        activities = (
            db.query(Activity)
            .filter(Activity.task_id == task.id)
            .order_by(Activity.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_activity_to_dict(a) for a in activities]


def _project_repo_to_dict(r) -> dict:
    return {
        "id": r.id,
        "project_id": r.project_id,
        "name": r.name,
        "repo_path": r.repo_path or "",
        "repo_url": r.repo_url or "",
        "default_branch": r.default_branch or "main",
        "worktree_freshness": getattr(r, "worktree_freshness", None) or "always_latest",
        "is_primary": bool(r.is_primary),
        # AP-302: token value is never exposed — only presence + validity.
        "has_token": bool(getattr(r, "access_token", None)),
        "token_valid": getattr(r, "token_valid", None),
        "token_checked_at": (
            r.token_checked_at.isoformat()
            if getattr(r, "token_checked_at", None) else None
        ),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def list_project_repos(project_id: str, actor: str = "system") -> list[dict]:
    """AP-121: enumerate repos attached to a project."""
    from backend.models import ProjectRepo
    with _session() as db:
        require_project_access(db, actor, project_id, "read")
        rows = (db.query(ProjectRepo)
                  .filter(ProjectRepo.project_id == project_id)
                  .order_by(ProjectRepo.is_primary.desc(),
                            ProjectRepo.created_at.asc())
                  .all())
        return [_project_repo_to_dict(r) for r in rows]


def update_project_repo(project_id: str, repo_name: str, *,
                        repo_url: Optional[str] = None,
                        repo_path: Optional[str] = None,
                        default_branch: Optional[str] = None,
                        worktree_freshness: Optional[str] = None) -> dict:
    """AP-197: update an existing project repo (e.g. connect a remote URL).

    This is the multi-repo equivalent of editing `Project.repo_url` — needed so
    a project can be pointed at a git remote so the daemon clones it instead of
    worktree-ing off a (possibly TCC-blocked) local path. Returns the updated
    row dict, or `{"error": ...}`.
    """
    from backend.models import ProjectRepo
    with _session() as db:
        row = (db.query(ProjectRepo)
                 .filter(ProjectRepo.project_id == project_id,
                         ProjectRepo.name == repo_name)
                 .first())
        if not row:
            return {"error": f"Repo '{repo_name}' not found on project"}
        if repo_url is not None:
            row.repo_url = repo_url.strip() or None
        if repo_path is not None:
            rp = repo_path.strip()
            if rp and not (rp.startswith("/") or rp.startswith("~")):
                return {"error": (
                    f"repo_path must be an absolute host path or ~-anchored "
                    f"(got {rp!r})")}
            row.repo_path = rp or None
        if default_branch is not None:
            row.default_branch = default_branch.strip() or "main"
        if worktree_freshness is not None:
            wf = worktree_freshness.strip() or "always_latest"
            if wf not in ("always_latest", "new_only", "pinned"):
                return {"error": f"invalid worktree_freshness: {wf!r}"}
            row.worktree_freshness = wf
        db.commit()
        db.refresh(row)
        return _project_repo_to_dict(row)


def add_project_repo(project_id: str, *, name: str,
                     repo_path: str = "", repo_url: str = "",
                     default_branch: str = "main",
                     is_primary: bool = False) -> dict:
    """AP-121: attach a repo to a project. If `is_primary=True`, demotes
    any existing primary in the same project (only one primary at a
    time). Returns the new row's dict.
    """
    from backend.models import ProjectRepo
    name = (name or "").strip()
    if not name:
        return {"error": "name is required"}
    repo_path = (repo_path or "").strip()
    if not (repo_path or repo_url):
        return {"error": "repo_path or repo_url is required"}
    # repo_path is a HOST path the daemon worktrees off — it must be
    # absolute (or ~-anchored to the host home). A relative path (e.g. a
    # dropped leading slash, "Users/me/proj") can't be resolved on the host:
    # the daemon's worktree add silently no-ops and the agent is stranded
    # with no repo. Reject at registration instead. (Do NOT expanduser here —
    # the backend runs in docker where ~ is /root, not the host home.)
    if repo_path and not (repo_path.startswith("/") or repo_path.startswith("~")):
        return {"error": (
            f"repo_path must be an absolute host path or ~-anchored "
            f"(got {repo_path!r})")}
    with _session() as db:
        if not db.get(Project, project_id):
            return {"error": "Project not found"}
        # Name collision?
        if (db.query(ProjectRepo)
              .filter(ProjectRepo.project_id == project_id,
                      ProjectRepo.name == name)
              .first()):
            return {"error": f"Repo '{name}' already attached to project"}
        if is_primary:
            (db.query(ProjectRepo)
               .filter(ProjectRepo.project_id == project_id,
                       ProjectRepo.is_primary == True)  # noqa: E712
               .update({"is_primary": False}))
        # If no repos yet for this project, the first one is implicitly
        # primary so dispatch's "primary repo" fallback always resolves.
        existing_any = (db.query(ProjectRepo)
                          .filter(ProjectRepo.project_id == project_id)
                          .first())
        effective_primary = is_primary or (existing_any is None)
        row = ProjectRepo(
            project_id=project_id,
            name=name,
            repo_path=repo_path or None,
            repo_url=repo_url or None,
            default_branch=default_branch or "main",
            is_primary=effective_primary,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _project_repo_to_dict(row)


def remove_project_repo(project_id: str, repo_name: str) -> bool:
    """AP-121: detach a repo from a project. Returns True if removed."""
    from backend.models import ProjectRepo
    with _session() as db:
        row = (db.query(ProjectRepo)
                 .filter(ProjectRepo.project_id == project_id,
                         ProjectRepo.name == repo_name)
                 .first())
        if not row:
            return False
        was_primary = row.is_primary
        db.delete(row)
        # Flush the delete before the promotion query — autoflush is off, so
        # otherwise the SELECT still sees the doomed row and "promotes" it.
        db.flush()
        if was_primary:
            # Promote the next-oldest repo to primary so dispatch still
            # has a fallback target. If none remain, leave it — the
            # project becomes repo-less and tasks targeting "primary"
            # error cleanly at dispatch.
            next_row = (db.query(ProjectRepo)
                          .filter(ProjectRepo.project_id == project_id)
                          .order_by(ProjectRepo.created_at.asc())
                          .first())
            if next_row:
                next_row.is_primary = True
        db.commit()
        return True


def set_project_repo_token(project_id: str, repo_name: str,
                           token: str) -> dict | None:
    """AP-302: store (or clear) a git token on a project repo, then probe
    its validity against the repo's git remote. Returns the repo dict
    (token value omitted). None if the repo doesn't exist.

    An empty token clears the token and its cached validity.
    """
    from backend.models import ProjectRepo
    from backend import repo_tokens
    token = (token or "").strip()
    with _session() as db:
        row = (db.query(ProjectRepo)
                 .filter(ProjectRepo.project_id == project_id,
                         ProjectRepo.name == repo_name)
                 .first())
        if not row:
            return None
        if not token:
            row.access_token = None
            row.token_valid = None
            row.token_checked_at = None
        else:
            valid, _ = repo_tokens.verify_git_token(token, row.repo_url)
            row.access_token = token
            row.token_valid = valid
            row.token_checked_at = _dt.now(_tz.utc)
        db.commit()
        db.refresh(row)
        return _project_repo_to_dict(row)


def check_project_repo_token(project_id: str, repo_name: str) -> dict | None:
    """AP-302: re-probe a stored project-repo token's validity. Returns the
    repo dict, or None if the repo doesn't exist. No-op (returns dict with
    token_valid unchanged-None) when no token is stored."""
    from backend.models import ProjectRepo
    from backend import repo_tokens
    with _session() as db:
        row = (db.query(ProjectRepo)
                 .filter(ProjectRepo.project_id == project_id,
                         ProjectRepo.name == repo_name)
                 .first())
        if not row:
            return None
        if not row.access_token:
            return _project_repo_to_dict(row)
        valid, _ = repo_tokens.verify_git_token(row.access_token, row.repo_url)
        row.token_valid = valid
        row.token_checked_at = _dt.now(_tz.utc)
        db.commit()
        db.refresh(row)
        return _project_repo_to_dict(row)


def set_profile_git_token(profile_id: str, token: str) -> dict | None:
    """AP-302: store (or clear) an agent/user's personal git token and probe
    it (no specific repo → validates the token authenticates). Returns the
    profile dict (token value omitted). None if the profile doesn't exist."""
    from backend import repo_tokens
    token = (token or "").strip()
    with _session() as db:
        p = db.get(Profile, profile_id)
        if not p:
            return None
        if not token:
            p.git_token = None
            p.git_token_valid = None
            p.git_token_checked_at = None
        else:
            valid, _ = repo_tokens.verify_git_token(token, None)
            p.git_token = token
            p.git_token_valid = valid
            p.git_token_checked_at = _dt.now(_tz.utc)
        db.commit()
        db.refresh(p)
        return _profile_to_dict(p)


def check_profile_git_token(profile_id: str) -> dict | None:
    """AP-302: re-probe a stored profile git token's validity."""
    from backend import repo_tokens
    with _session() as db:
        p = db.get(Profile, profile_id)
        if not p:
            return None
        if not p.git_token:
            return _profile_to_dict(p)
        valid, _ = repo_tokens.verify_git_token(p.git_token, None)
        p.git_token_valid = valid
        p.git_token_checked_at = _dt.now(_tz.utc)
        db.commit()
        db.refresh(p)
        return _profile_to_dict(p)


def resolve_git_token(project_id: str, repo_name: str | None,
                      profile_id: str | None) -> str | None:
    """AP-302: pick the git token a dispatch should use. Repo-level token
    wins; falls back to the agent/profile's personal token. None if neither
    is set. Used at dispatch to inject GH_TOKEN."""
    from backend.models import ProjectRepo
    with _session() as db:
        if project_id:
            q = db.query(ProjectRepo).filter(
                ProjectRepo.project_id == project_id)
            if repo_name:
                q = q.filter(ProjectRepo.name == repo_name)
            else:
                q = q.filter(ProjectRepo.is_primary == True)  # noqa: E712
            row = q.first()
            if row and row.access_token:
                return row.access_token
        if profile_id:
            p = db.get(Profile, profile_id)
            if p and p.git_token:
                return p.git_token
    return None


def resolve_project_repo(project_id: str, repo_name: str | None) -> dict | None:
    """AP-121: pick the repo a task / run should materialize against.

    - If `repo_name` is given, look it up exactly; return None if not
      found (caller decides whether to error).
    - If `repo_name` is None, return the project's primary repo.
    - If the project has no project_repos rows AT ALL (legacy, pre-
      backfill), fall back to a synthetic dict built from
      `projects.repo_path` / `repo_url` so old dispatch paths keep
      working without a hard cutover.
    """
    from backend.models import ProjectRepo
    with _session() as db:
        if repo_name:
            row = (db.query(ProjectRepo)
                     .filter(ProjectRepo.project_id == project_id,
                             ProjectRepo.name == repo_name)
                     .first())
            return _project_repo_to_dict(row) if row else None
        row = (db.query(ProjectRepo)
                 .filter(ProjectRepo.project_id == project_id,
                         ProjectRepo.is_primary == True)  # noqa: E712
                 .first())
        if row:
            return _project_repo_to_dict(row)
        # Legacy fallback.
        proj = db.get(Project, project_id)
        if proj and (proj.repo_path or proj.repo_url):
            return {
                "id": "",
                "project_id": project_id,
                "name": "primary",
                "repo_path": proj.repo_path or "",
                "repo_url": proj.repo_url or "",
                "default_branch": "main",
                "is_primary": True,
                "created_at": None,
            }
        return None


def get_webhook_config(project_id: str) -> dict | None:
    """Return the project's webhook config, falling back to DEFAULT_WEBHOOK_RULES."""
    with _session() as db:
        p = db.get(Project, project_id)
        if not p:
            return None
        if p.webhook_config:
            import json
            try:
                return json.loads(p.webhook_config)
            except (json.JSONDecodeError, ValueError):
                pass
        return {"enabled": True, "rules": agent_notifier.DEFAULT_WEBHOOK_RULES}


def set_webhook_config(project_id: str, enabled: bool, rules: list[dict], token: str = "") -> dict:
    """Validate and save webhook config for a project."""
    import json
    _valid_receivers = {"assignee", "bots", "members"}
    for rule in rules:
        if "event" not in rule or "receivers" not in rule:
            raise ValueError("Each rule must have 'event' and 'receivers' keys")
        if rule["receivers"] not in _valid_receivers:
            raise ValueError(f"Invalid receivers '{rule['receivers']}'; must be one of {_valid_receivers}")

    with _session() as db:
        p = db.get(Project, project_id)
        if not p:
            raise ValueError(f"Project {project_id} not found")
        cfg = {"enabled": enabled, "rules": rules}
        if token:
            cfg["token"] = token
        p.webhook_config = json.dumps(cfg)
        db.commit()
        return cfg


def get_project_activity(
    project_id: str,
    limit: int = 50,
    actor: str = "system",
) -> list[dict]:
    """Return recent activity across all tasks in a project, newest first."""
    with _session() as db:
        require_project_access(db, actor, project_id, "read")
        activities = (
            db.query(Activity)
            .filter(Activity.project_id == project_id)
            .order_by(Activity.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": a.id,
                "project_id": a.project_id,
                "task_id": a.task_id,
                "actor": a.actor,
                "action": a.action,
                "detail": a.detail,
                "created_at": a.created_at.isoformat(),
            }
            for a in activities
        ]


def get_changes_since(task_id: str, since: str) -> dict:
    from datetime import datetime, timezone

    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))

    with _session() as db:
        task = db.get(Task, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        new_activities = (
            db.query(Activity)
            .filter(Activity.task_id == task_id, Activity.created_at > since_dt)
            .order_by(Activity.created_at.asc())
            .all()
        )

        return {
            "task": _task_to_dict(task, attachments_count=_attachment_count(db, task.id)),
            "new_activities": [_activity_to_dict(a) for a in new_activities],
            "has_changes": len(new_activities) > 0,
        }


# ── Board view ───────────────────────────────────────────────────────────

def get_board(project_id: str) -> dict:
    with _session() as db:
        project = db.get(Project, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        from backend.repos import tasks as core_tasks_repo

        statuses = db.query(Status).order_by(Status.position).all()
        board: dict[str, list[dict]] = {s.name: [] for s in statuses}

        tasks = (
            core_tasks_repo.with_list_relations(db.query(Task))
            .filter(Task.project_id == project_id)
            .order_by(Task.updated_at.desc())
            .all()
        )
        ids = [t.id for t in tasks]
        counts = _batch_attachment_counts(db, ids)
        commit_counts = core_tasks_repo.batch_commit_counts(db, ids)
        active = _active_run_agents(db, ids)  # so the board card glow lights up
        for t in tasks:
            d = _task_to_dict(t, attachments_count=counts.get(t.id, 0),
                               commits_count=commit_counts.get(t.id, 0))
            info = active.get(t.id)
            d["agent_active"] = info is not None
            if info:
                d["active_agent_id"] = info["agent_id"]
                d["active_agent_name"] = info["agent_name"]
            board[t.status.name].append(d)

        return {
            "project": _project_to_dict(project),
            "columns": board,
        }

def get_roadmap(project_id: str, group_by: str = "epic") -> dict:
    """Return roadmap data: tasks grouped by epic or tag, with milestones and date range."""
    with _session() as db:
        project = db.get(Project, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        from backend.repos import tasks as core_tasks_repo
        from backend.repos import task_graph as graph_repo

        tasks = (
            core_tasks_repo.with_list_relations(db.query(Task))
            .filter(Task.project_id == project_id)
            .order_by(Task.created_at.asc())
            .all()
        )

        STATUS_PROGRESS = {"done": 100, "review": 75, "in_progress": 50, "todo": 25, "backlog": 0}

        # Group by epic or tag. For epic grouping we also remember the
        # epic id + color per group so the UI can link to the epic page.
        groups: dict[str, list] = {}
        group_meta: dict[str, dict] = {}
        all_dates = []

        # AP-496: dependency edges + blocked flags for the whole project, so
        # the roadmap can draw the graph without a request per task.
        task_ids = [t.id for t in tasks]
        neighbors = graph_repo.neighbor_tasks(db, task_ids)
        sub_counts = graph_repo.subtask_counts(db, task_ids)
        dependencies = [
            {"id": d.id, "task_id": d.task_id, "depends_on_id": d.depends_on_id}
            for d in graph_repo.list_dependencies(db, project_id)
        ]

        for t in tasks:
            if group_by == "tag":
                tags = [tag.strip() for tag in t.tags.split(",") if tag.strip()] if t.tags else []
                group_key = tags[0] if tags else "Ungrouped"
            else:
                group_key = t.epic.title if t.epic else "Ungrouped"
                if t.epic and group_key not in group_meta:
                    group_meta[group_key] = {"id": t.epic.id, "color": t.epic.color}

            start = t.start_date.isoformat() if t.start_date else t.created_at.isoformat()
            end = t.due_date.isoformat() if t.due_date else None
            status_name = t.status.name
            progress = STATUS_PROGRESS.get(status_name, 0)

            blocked_by = neighbors.get(t.id, {}).get("blocked_by", [])
            task_data = {
                "id": t.id,
                "key": t.key or t.id,
                "title": t.title,
                "status": status_name,
                "priority": t.priority.value,
                "assignee": t.assignee or None,
                "start": start,
                "end": end,
                "progress": progress,
                # AP-496 graph fields
                "parent_id": t.parent_id,
                "milestone_id": t.milestone_id,
                "subtasks": sub_counts.get(t.id, {"total": 0, "done": 0}),
                "blocked_by": blocked_by,
                "blocks": neighbors.get(t.id, {}).get("blocks", []),
                "is_blocked": any(b["status"] != "done" for b in blocked_by),
            }

            groups.setdefault(group_key, []).append(task_data)
            all_dates.append(start)
            if end:
                all_dates.append(end)

        # Build summaries
        group_list = []
        for name, tasks_in_group in groups.items():
            total = len(tasks_in_group)
            done = sum(1 for t in tasks_in_group if t["progress"] == 100)
            in_flight = sum(1 for t in tasks_in_group if 0 < t["progress"] < 100)
            meta = group_meta.get(name, {})
            group_list.append({
                "id": meta.get("id"),
                "name": name,
                "color": meta.get("color"),
                "tasks": tasks_in_group,
                "total": total,
                "done": done,
                "in_progress": in_flight,
                "progress": round(sum(t["progress"] for t in tasks_in_group) / total) if total else 0,
            })

        # Sort: groups with in-progress work first, then by progress desc
        group_list.sort(key=lambda e: (-e["in_progress"], -e["progress"], e["name"]))

        # AP-496: milestones are real, dated rows now (was: "any done task"),
        # with progress derived from the tasks pointing at them.
        from backend import task_graph as graph_service

        ms_rows = graph_repo.list_milestones(db, project_id)
        ms_counts = graph_repo.milestone_counts(db, [m.id for m in ms_rows])
        milestones = [graph_service._milestone_to_dict(m, ms_counts.get(m.id))
                      for m in ms_rows]
        # Legacy key kept for the timeline's "recently shipped" strip.
        recent_completions = sorted(
            [{"id": t.id, "title": t.title, "date": t.updated_at.isoformat()}
             for t in tasks if t.status.name == "done"],
            key=lambda m: m["date"], reverse=True)[:10]

        return {
            "project": {"id": project.id, "name": project.name},
            "epics": group_list,
            "milestones": milestones,
            "recent_completions": recent_completions,
            "dependencies": dependencies,
            "summary": {
                "total_tasks": sum(e["total"] for e in group_list),
                "total_done": sum(e["done"] for e in group_list),
                "total_epics": len(group_list),
                "total_milestones": len(milestones),
                "blocked_tasks": sum(
                    1 for e in group_list for t in e["tasks"] if t["is_blocked"]),
            },
        }


# ── Status operations ───────────────────────────────────────────────────

def list_statuses() -> list[dict]:
    with _session() as db:
        statuses = db.query(Status).order_by(Status.position).all()
        return [{"id": s.id, "name": s.name, "position": s.position} for s in statuses]


def create_status(name: str, position: int = 0) -> dict:
    with _session() as db:
        s = Status(name=name, position=position)
        db.add(s)
        db.commit()
        db.refresh(s)
        return {"id": s.id, "name": s.name, "position": s.position}


def delete_status(status_id: str) -> bool:
    with _session() as db:
        s = db.get(Status, status_id)
        if not s:
            return False
        db.delete(s)
        db.commit()
        return True


# ── Role & Permission operations ────────────────────────────────────────

def list_roles() -> list[dict]:
    with _session() as db:
        roles = db.query(Role).order_by(Role.name).all()
        result = []
        for r in roles:
            perms = [rp.permission.codename for rp in r.permissions]
            result.append({"id": r.id, "name": r.name, "permissions": perms})
        return result


def list_permissions() -> list[dict]:
    with _session() as db:
        perms = db.query(Permission).order_by(Permission.codename).all()
        return [{"id": p.id, "codename": p.codename, "description": p.description} for p in perms]


def create_permission(codename: str, description: str = None) -> dict:
    with _session() as db:
        # Check if already exists
        existing = db.query(Permission).filter_by(codename=codename).first()
        if existing:
            raise ValueError(f"Permission '{codename}' already exists.")
        
        p = Permission(codename=codename, description=description)
        db.add(p)
        db.commit()
        db.refresh(p)
        return {"id": p.id, "codename": p.codename, "description": p.description}


def create_role(name: str, description: str = None, permissions: list[str] = []) -> dict:
    """Dynamically create a new role and optionally assign permissions."""
    name = name.lower().strip()
    with _session() as db:
        if db.query(Role).filter(Role.name == name).first():
            raise ValueError(f"Role '{name}' already exists.")
        
        role = Role(name=name, description=description)
        db.add(role)
        db.commit()
        db.refresh(role)

        for codename in permissions:
            perm = db.query(Permission).filter(Permission.codename == codename).first()
            if perm:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))

        db.commit()
        db.refresh(role)
        return {
            "id": role.id,
            "name": role.name,
            "description": role.description,
            "permissions": [rp.permission.codename for rp in role.permissions]
        }


def delete_role(role_id: str) -> bool:
    with _session() as db:
        r = db.get(Role, role_id)
        if not r:
            return False
        db.delete(r)
        db.commit()
        return True


def grant_role_permission(role_name: str, codename: str) -> bool:
    """Grant a permission to a role. Creates the permission if it doesn't exist."""
    with _session() as db:
        role = db.query(Role).filter(Role.name == role_name).first()
        if not role:
            return False

        perm = db.query(Permission).filter(Permission.codename == codename).first()
        if not perm:
            perm = Permission(codename=codename)
            db.add(perm)
            db.flush()

        existing = db.query(RolePermission).filter_by(role_id=role.id, permission_id=perm.id).first()
        if not existing:
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))
            db.commit()

        return True


def revoke_role_permission(role_name: str, codename: str) -> bool:
    with _session() as db:
        role = db.query(Role).filter(Role.name == role_name).first()
        perm = db.query(Permission).filter(Permission.codename == codename).first()
        if not role or not perm:
            return False
        rp = db.query(RolePermission).filter_by(role_id=role.id, permission_id=perm.id).first()
        if not rp:
            return False
        db.delete(rp)
        db.commit()
        return True


def grant_profile_permission(profile_id: str, codename: str) -> dict:
    """Grant an extra permission directly to a profile."""
    with _session() as db:
        prof = db.get(Profile, profile_id)
        if not prof:
            raise ValueError(f"Profile {profile_id} not found")

        perm = db.query(Permission).filter(Permission.codename == codename).first()
        if not perm:
            perm = Permission(codename=codename)
            db.add(perm)
            db.flush()

        existing = db.query(ProfilePermission).filter_by(profile_id=prof.id, permission_id=perm.id).first()
        if not existing:
            db.add(ProfilePermission(profile_id=prof.id, permission_id=perm.id))
            db.commit()

        return {"profile": prof.name, "permission": codename}


def revoke_profile_permission(profile_id: str, codename: str) -> bool:
    with _session() as db:
        prof = db.get(Profile, profile_id)
        perm = db.query(Permission).filter(Permission.codename == codename).first()
        if not prof or not perm:
            return False
        pp = db.query(ProfilePermission).filter_by(profile_id=prof.id, permission_id=perm.id).first()
        if not pp:
            return False
        db.delete(pp)
        db.commit()
        return True


# ── Attachment operations ────────────────────────────────────────────────
# AP-152: the actual logic lives in `backend.attachments`. These remain
# as thin back-compat shims so existing REST + MCP imports keep working.

from backend import attachments as _attachments


def add_attachment(
    task_id: str,
    filename: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
    uploaded_by: str = "system",
    actor: str = "system",
) -> dict:
    authorize_task_access(task_id, actor, "write")
    return _attachments.add(
        task_id=task_id, filename=filename, file_bytes=file_bytes,
        content_type=content_type, uploaded_by=uploaded_by,
    )


def list_attachments(task_id: str, actor: str = "system") -> list[dict]:
    authorize_task_access(task_id, actor, "read")
    return _attachments.list_for_task(task_id)


def list_project_attachments(
    project_id: str,
    actor: str = "system",
) -> list[dict]:
    authorize_project_access(project_id, actor, "read")
    return _attachments.list_for_project(project_id)


def get_attachment(
    attachment_id: str,
    actor: str = "system",
) -> tuple[dict, str] | None:
    authorize_attachment_access(attachment_id, actor, "read")
    return _attachments.get(attachment_id)


def get_attachment_bytes(
    attachment_id: str,
    actor: str = "system",
) -> tuple[dict, bytes] | None:
    authorize_attachment_access(attachment_id, actor, "read")
    return _attachments.get_bytes(attachment_id)


def delete_attachment(attachment_id: str, actor: str = "system") -> bool:
    authorize_attachment_access(attachment_id, actor, "write")
    return _attachments.delete(attachment_id)


# ── Profile operations ──────────────────────────────────────────────────

def validate_api_key(api_key: str) -> dict:
    """Validate API key and return profile dict. Use this for MCP authentication.

    Cross-org lookup (we don't know the caller's org until we resolve the key),
    so it runs privileged. The MCP middleware then pins the resolved org for
    the rest of the request so RLS scopes tool calls."""
    if not api_key:
        raise ValueError("API key required")
    with privileged(), _session() as db:
        p = db.query(Profile).filter(Profile.api_key == api_key).first()
        if not p:
            raise ValueError("Invalid API key")
        return _profile_to_dict(p)


def create_profile(name: str, display_name: str = "", role: str = None,
                    roles: list[str] = None, account_type: str = "human",
                    avatar_url: str = "", password: str = "") -> dict:
    """Internal use. Returns profile dict WITH api_key.

    Roles (permission tiers) are decoupled from account_type (what the identity
    IS). Pass `roles` (a list) for the M2M; the legacy single `role` arg is
    still accepted and wrapped into a one-element list."""
    role_names = roles if roles is not None else ([role] if role else ["member"])
    with _session() as db:
        role_objs = _resolve_roles(db, role_names)
        password_hash = _hash_password(password) if password else ""
        profile = Profile(
            name=name,
            display_name=display_name or name,
            account_type=account_type,
            avatar_url=avatar_url,
            password_hash=password_hash,
            api_key=secrets.token_hex(32),
            roles=role_objs,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        res = _profile_to_dict(profile)
        res["api_key"] = profile.api_key  # Include key only on creation
        return res


def create_service_account(name: str, display_name: str = "") -> dict:
    """Create an external-agent (service account) identity + API key.

    account_type=external_agent (an API-key-only identity for external systems);
    role=member (a real permission tier — the old 'bot' role is gone)."""
    return create_profile(name, display_name or name,
                           account_type="external_agent", roles=["member"])


def _create_org(db: Session, owner_display_name: str) -> Org:
    """Create a fresh org for a new signup. Caller must be in a privileged
    session (org context is None during signup)."""
    label = (owner_display_name or "My").strip()
    org = Org(name=f"{label}'s Org")
    db.add(org)
    db.flush()  # assign org.id
    return org


def seed_org_defaults(org_id: str) -> None:
    """Seed a freshly-created org with its default agent team (Conductor,
    Planner, Reviewer, Implementers, DevOps from templates) + the Agentira
    Guide. Best-effort; never blocks org creation. Runs privileged so it can
    write across RLS while stamping the explicit org_id.

    Call this AFTER the org row is committed (the seeders use their own
    sessions and must see the org for the FK)."""
    from backend import agent_templates
    from backend.forge.conductor import get_or_create_conductor
    from backend.forge.concierge import get_or_create_concierge
    with privileged():
        try:
            r = agent_templates.seed_all(org_id)
            logger.info("org %s seeded agents: %s", org_id, r.get("created"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("seed_all failed for org %s: %s", org_id, exc)
        for fn in (get_or_create_conductor, get_or_create_concierge):
            try:
                fn(org_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s failed for org %s: %s", fn.__name__, org_id, exc)


# ── Invite-only signup ─────────────────────────────────────────────────────
# Open self-serve signup is disabled. Accounts are created only by accepting an
# invite code:
#   - admin invite  (org_id NULL, role=admin)  → creates a new org + admin
#   - member invite (org_id set,  role=member) → joins that org (capped)
# Operator issues admin invites (scripts/create_invite.py); admins issue member
# invites in-app (POST /api/invites).

from datetime import datetime as _dt, timezone as _tz, timedelta  # noqa: E402


def _utcnow():
    return _dt.now(_tz.utc)


def create_invite(*, role: str, org_id: str | None, email: str | None = None,
                  invited_by: str | None = None, ttl_days: int = 14) -> dict:
    """Create an invite code. Admin invites (role='admin') carry no org;
    member invites must carry the inviter's org_id and are capped by
    Org.max_members."""
    from backend.models import Invite
    role = role if role in ("admin", "member") else "member"
    with privileged(), _session() as db:
        if role == "member":
            if not org_id:
                raise ValueError("member invite requires org_id")
            _assert_member_capacity(db, org_id)
        code = secrets.token_urlsafe(24)
        inv = Invite(
            code=code, role=role, org_id=org_id, email=email,
            invited_by=invited_by,
            expires_at=_utcnow() + timedelta(days=ttl_days),
        )
        db.add(inv)
        db.commit()
        return {"code": code, "role": role, "org_id": org_id,
                "expires_at": inv.expires_at.isoformat()}


def get_invite(code: str) -> dict | None:
    """Public: describe an invite for the signup page (no secrets)."""
    from backend.models import Invite
    with privileged(), _session() as db:
        inv = db.query(Invite).filter(Invite.code == code).first()
        if not inv:
            return None
        org_name = None
        if inv.org_id:
            org = db.get(Org, inv.org_id)
            org_name = org.name if org else None
        return {
            "role": inv.role,
            "email": inv.email,
            "org_id": inv.org_id,
            "org_name": org_name,
            "accepted": inv.accepted_at is not None,
            "expired": bool(inv.expires_at and inv.expires_at < _utcnow()),
        }


def _assert_member_capacity(db: Session, org_id: str) -> None:
    """Raise if the org is already at its member cap (non-bot profiles beyond
    the founding admin)."""
    org = db.get(Org, org_id)
    if not org:
        raise ValueError("org not found")
    non_bot = (db.query(Profile)
               .filter(Profile.org_id == org_id, Profile.account_type == "human")
               .count())
    # founding admin doesn't count against the member cap
    if max(non_bot - 1, 0) >= org.max_members:
        raise ValueError(f"org member limit ({org.max_members}) reached")


def accept_invite(code: str, *, name: str, password: str = "",
                  display_name: str = "", email: str = "") -> dict:
    """Accept an invite by code, creating the profile (and org for admin
    invites). Returns profile + api_key. Privileged: no org context yet.

    AP-306: email is required for every account. The submitted email wins
    over any address stored on the invite."""
    from backend.models import Invite
    email = (email or "").strip().lower()
    if "@" not in email:
        raise ValueError("a valid email is required")
    with privileged(), _session() as db:
        inv = db.query(Invite).filter(Invite.code == code).first()
        if not inv:
            raise ValueError("invalid invite")
        if inv.accepted_at is not None:
            raise ValueError("invite already used")
        if inv.expires_at and inv.expires_at < _utcnow():
            raise ValueError("invite expired")
        if db.query(Profile).filter(Profile.name == name).first():
            raise ValueError(f"username '{name}' is taken")
        if db.query(Profile).filter(Profile.email == email).first():
            raise ValueError("that email is already in use")

        new_org = False
        if inv.role == "admin":
            org = _create_org(db, display_name or name)
            org_id = org.id
            role_objs = _resolve_roles(db, ["admin"])
            new_org = True
        else:
            if not inv.org_id:
                raise ValueError("malformed member invite")
            _assert_member_capacity(db, inv.org_id)
            org_id = inv.org_id
            role_objs = _resolve_roles(db, ["member"])

        profile = Profile(
            org_id=org_id,
            name=name,
            display_name=display_name or name,
            email=email,
            account_type="human",
            roles=role_objs,
            password_hash=_hash_password(password) if password else "",
            api_key=secrets.token_hex(32),
        )
        db.add(profile)
        db.flush()
        inv.accepted_at = _utcnow()
        inv.accepted_profile_id = profile.id
        db.commit()
        db.refresh(profile)
        res = _profile_to_dict(profile)
        res["api_key"] = profile.api_key
    # Seed the new org's default agents (after commit, outside the session).
    if new_org:
        seed_org_defaults(org_id)
    # AP-306: welcome email (best-effort; no-op if SMTP unconfigured).
    from backend import email_sender
    email_sender.send_welcome_email(email, display_name or name)
    return res


def authenticate_oauth(provider: str, provider_user_id: str, email: str | None = None,
                       display_name: str = "", avatar_url: str = "",
                       invite_code: str | None = None) -> dict:
    """Log in via OAuth — invite-only registration.

    - Existing OAuth link or matching email → log in.
    - New user WITH a valid invite_code → accept the invite (joins the org, or
      creates a new org for an admin invite) and link the OAuth account.
    - New user with no invite → rejected.

    Runs privileged: lookups are cross-org and registration predates RLS scope.
    """
    from backend.models import Invite
    with privileged(), _session() as db:
        # Existing OAuth link → log in.
        link = (db.query(OAuthAccount)
                .filter(OAuthAccount.provider == provider,
                        OAuthAccount.provider_user_id == provider_user_id)
                .first())
        if link:
            profile = db.query(Profile).get(link.profile_id)
            return _profile_to_dict(profile)

        # Existing profile by email → link this provider and log in.
        profile = None
        if email:
            profile = db.query(Profile).filter(Profile.email == email).first()

        new_org_id = None
        if not profile:
            # New user: require a valid invite.
            if not invite_code:
                raise ValueError("No account for this login. Ask your admin for an invite.")
            inv = db.query(Invite).filter(Invite.code == invite_code).first()
            if not inv or inv.accepted_at is not None or (
                    inv.expires_at and inv.expires_at < _utcnow()):
                raise ValueError("invalid or expired invite")

            if inv.role == "admin":
                org = _create_org(db, display_name or (email or "My"))
                org_id, role_objs = org.id, _resolve_roles(db, ["admin"])
                new_org_id = org.id
            else:
                if not inv.org_id:
                    raise ValueError("malformed member invite")
                _assert_member_capacity(db, inv.org_id)
                org_id, role_objs = inv.org_id, _resolve_roles(db, ["member"])

            base_name = (email.split("@")[0] if email else display_name.lower().replace(" ", "_"))[:60]
            name = base_name
            suffix = 1
            while db.query(Profile).filter(Profile.name == name).first():
                name = f"{base_name}_{suffix}"
                suffix += 1

            profile = Profile(
                org_id=org_id,
                name=name,
                display_name=display_name or name,
                email=email,
                account_type="human",
                roles=role_objs,
                avatar_url=avatar_url,
                api_key=secrets.token_hex(32),
            )
            db.add(profile)
            db.flush()
            inv.accepted_at = _utcnow()
            inv.accepted_profile_id = profile.id

        # Link the OAuth account (inherits the profile's org).
        db.add(OAuthAccount(
            org_id=profile.org_id,
            profile_id=profile.id,
            provider=provider,
            provider_user_id=provider_user_id,
        ))
        db.commit()
        db.refresh(profile)
        res = _profile_to_dict(profile)
    # Seed the new org's default agents (after commit, outside the session).
    if new_org_id:
        seed_org_defaults(new_org_id)
    return res


def list_profiles(role: Optional[str] = None) -> list[dict]:
    with _session() as db:
        q = _with_profile_relations(db.query(Profile))
        if role:
            q = q.filter(Profile.roles.any(Role.name == role))
        return [_profile_to_dict(p) for p in q.order_by(Profile.name).all()]


def list_service_accounts() -> list[dict]:
    """Service accounts: external-agent identities (API-key-only).

    Used by external systems (CI, plugins, external MCP/Claude sessions).
    Distinct from agentira_agent (dispatched/managed agents). Keyed on the
    stored account_type, not the retired 'bot' role."""
    with _session() as db:
        q = db.query(Profile).filter(Profile.account_type == "external_agent")
        return [_profile_to_dict(p) for p in q.order_by(Profile.name).all()]


def get_profile(profile_id: str) -> dict | None:
    with _session() as db:
        p = db.get(Profile, profile_id)
        return _profile_to_dict(p) if p else None


def get_service_account(profile_id: str) -> dict | None:
    """Returns an external-agent profile's details WITH api_key."""
    with _session() as db:
        p = db.get(Profile, profile_id)
        if not p or p.account_type != "external_agent":
            return None
        res = _profile_to_dict(p)
        res["api_key"] = p.api_key
        return res


def regenerate_api_key(profile_id: str) -> dict | None:
    """Rotate a service account's API key. Returns the profile WITH the new
    key, or None if it isn't an external-agent identity."""
    with _session() as db:
        p = db.get(Profile, profile_id)
        if not p or p.account_type != "external_agent":
            return None
        p.api_key = secrets.token_hex(32)
        db.commit()
        db.refresh(p)
        res = _profile_to_dict(p)
        res["api_key"] = p.api_key
        return res


def update_profile(profile_id: str, display_name: Optional[str] = None, role: Optional[str] = None, roles: Optional[list[str]] = None, avatar_url: Optional[str] = None, webhook_url: Optional[str] = None, email: Optional[str] = None) -> dict:
    with _session() as db:
        p = db.get(Profile, profile_id)
        if not p:
            raise ValueError(f"Profile {profile_id} not found")

        # TODO: Add actor check here if not already handled by caller (REST/MCP)
        # For now, we assume caller validates permissions.

        if display_name is not None:
            p.display_name = display_name
        # RBAC: assign one or more roles (admin-gated by the caller). `roles`
        # (the list) wins; the legacy single `role` is still accepted.
        if roles is not None:
            p.roles = _resolve_roles(db, roles)
        elif role is not None:
            p.roles = _resolve_roles(db, [role])
        if avatar_url is not None:
            p.avatar_url = avatar_url
        if webhook_url is not None:
            p.webhook_url = webhook_url
        if email is not None:
            # AP-306: admins set/backfill a member's email. Normalize + keep
            # globally unique.
            email = email.strip().lower()
            if "@" not in email:
                raise ValueError("a valid email is required")
            clash = db.query(Profile).filter(Profile.email == email,
                                             Profile.id != profile_id).first()
            if clash:
                raise ValueError("that email is already in use")
            p.email = email

        db.commit()
        db.refresh(p)
        return _profile_to_dict(p)


def delete_profile(profile_id: str) -> bool:
    with _session() as db:
        p = db.get(Profile, profile_id)
        if not p:
            return False
        # Clean up child rows that FK to this profile. SQLite ignores FKs by
        # default so the naive `db.delete(p)` worked there; Postgres rejects it.
        db.query(ProfilePermission).filter_by(profile_id=profile_id).delete()
        db.query(OAuthAccount).filter_by(profile_id=profile_id).delete()
        db.query(ProjectMember).filter_by(profile_id=profile_id).delete()
        db.query(Notification).filter_by(profile_id=profile_id).delete()
        # forge_agents.profile_id is nullable — null it so the agent definition
        # outlives its associated user account.
        from backend.forge.models import Agent as _ForgeAgent
        db.query(_ForgeAgent).filter_by(profile_id=profile_id).update(
            {"profile_id": None}, synchronize_session=False)
        db.delete(p)
        db.commit()
        return True


# ── Git Integration ──────────────────────────────────────────────────

def _commit_to_dict(c: TaskCommit) -> dict:
    return {
        "id": c.id,
        "task_id": c.task_id,
        "sha": c.sha,
        "message": c.message,
        "author": c.author,
        "branch": c.branch,
        "url": c.url,
        "repo": c.repo,
        "kind": c.kind,
        "pr_state": c.pr_state,
        "pr_number": c.pr_number,
        "committed_at": c.committed_at.isoformat() if c.committed_at else None,
        "created_at": c.created_at.isoformat(),
    }


def list_task_commits(task_id: str) -> list[dict]:
    with _session() as db:
        commits = db.query(TaskCommit).filter(TaskCommit.task_id == task_id).order_by(TaskCommit.committed_at.desc()).all()
        return [_commit_to_dict(c) for c in commits]


def suggest_branch_name(task_id: str) -> dict | None:
    """Generate a suggested branch name from task key + title."""
    import re
    with _session() as db:
        task = _resolve_task(db, task_id)
        if not task:
            return None
        key = (task.key or task.id).lower()
        slug = re.sub(r'[^a-z0-9]+', '-', task.title.lower()).strip('-')[:50]
        name = f"task/{key}-{slug}"
        return {"branch": name, "command": f"git checkout -b {name}"}


def link_commit(task_id: str, *, sha: str, message: str = "", author: str = "",
                branch: str = "", url: str = "", repo: str = "",
                committed_at: str | None = None) -> dict:
    from datetime import datetime as dt, timezone as tz
    with _session() as db:
        task = _resolve_task(db, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        task_id = task.id
        # Avoid duplicate sha per task
        existing = db.query(TaskCommit).filter_by(task_id=task_id, sha=sha).first()
        if existing:
            return _commit_to_dict(existing)
        ts = None
        if committed_at:
            ts = dt.fromisoformat(committed_at.replace("Z", "+00:00"))
        c = TaskCommit(
            task_id=task_id, sha=sha, message=message, author=author,
            branch=branch, url=url, repo=repo, kind="commit", committed_at=ts,
        )
        db.add(c)
        # Auto-sync: set task.branch from commit if empty
        if branch and not task.branch:
            task.branch = branch
        _log_activity(db, author or "system", "task.commit.linked",
                      f"Commit {sha[:7]}: {message[:80]}",
                      project_id=task.project_id, task_id=task_id)
        db.commit()
        db.refresh(c)
        return _commit_to_dict(c)


def link_pr(task_id: str, *, pr_number: int, title: str = "", author: str = "",
            branch: str = "", url: str = "", repo: str = "",
            state: str = "open") -> dict:
    with _session() as db:
        task = _resolve_task(db, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        task_id = task.id
        # repo in the filter: a multi-repo task can have the same PR number
        # in two repos — without it the second repo's PR overwrites the first.
        existing = db.query(TaskCommit).filter_by(task_id=task_id, pr_number=pr_number, kind="pr", repo=repo).first()
        if existing:
            existing.pr_state = state
            # Auto-sync: update pr_url on state changes too
            if url and not task.pr_url:
                task.pr_url = url
            db.commit()
            db.refresh(existing)
            return _commit_to_dict(existing)
        c = TaskCommit(
            task_id=task_id, sha=f"pr-{pr_number}", message=title, author=author,
            branch=branch, url=url, repo=repo, kind="pr",
            pr_state=state, pr_number=pr_number,
        )
        db.add(c)
        # Auto-sync: set task.pr_url and task.branch from PR
        if url:
            task.pr_url = url
        if branch and not task.branch:
            task.branch = branch
        _log_activity(db, author or "system", "task.pr.linked",
                      f"PR #{pr_number}: {title[:80]}",
                      project_id=task.project_id, task_id=task_id)
        db.commit()
        db.refresh(c)
        return _commit_to_dict(c)


def process_github_webhook(payload: dict) -> list[dict]:
    """Parse a GitHub push or PR webhook and link commits/PRs to tasks.

    Task IDs are detected in commit messages and PR titles/body using
    patterns like [TASK-abc123] or task:abc123.
    """
    import re
    task_id_pattern = re.compile(r'(?:\[TASK[- ]?([a-f0-9]{12})\]|task[: ]([a-f0-9]{12}))', re.IGNORECASE)
    task_key_pattern = re.compile(r'\[([A-Z]{2,10}-\d+)\]', re.IGNORECASE)
    results = []

    def extract_task_ids(text: str) -> list[str]:
        ids = [m.group(1) or m.group(2) for m in task_id_pattern.finditer(text or "")]
        keys = [m.group(1).upper() for m in task_key_pattern.finditer(text or "")]
        return ids + keys

    # Push event — commits
    if "commits" in payload:
        repo = payload.get("repository", {}).get("full_name", "")
        branch = (payload.get("ref", "").replace("refs/heads/", ""))
        for commit in payload.get("commits", []):
            task_ids = extract_task_ids(commit.get("message", ""))
            for tid in task_ids:
                try:
                    r = link_commit(
                        tid, sha=commit.get("id", ""),
                        message=commit.get("message", ""),
                        author=commit.get("author", {}).get("name", ""),
                        branch=branch, url=commit.get("url", ""),
                        repo=repo, committed_at=commit.get("timestamp"),
                    )
                    results.append(r)
                except ValueError:
                    pass

    # PR event
    if "pull_request" in payload:
        pr = payload["pull_request"]
        repo = payload.get("repository", {}).get("full_name", "")
        title = pr.get("title", "")
        body = pr.get("body", "") or ""
        task_ids = extract_task_ids(title) + extract_task_ids(body)
        state = "merged" if pr.get("merged") else pr.get("state", "open")
        for tid in set(task_ids):
            try:
                r = link_pr(
                    tid, pr_number=pr.get("number", 0),
                    title=title, author=pr.get("user", {}).get("login", ""),
                    branch=pr.get("head", {}).get("ref", ""),
                    url=pr.get("html_url", ""), repo=repo, state=state,
                )
                results.append(r)
            except ValueError:
                pass

    return results


# ── Bootstrap ────────────────────────────────────────────────────────────

def _seed_defaults(db: Session) -> None:
    """Create default roles, statuses, permissions, and transition rules."""

    # Roles — permission tiers only. The old 'bot' role is retired: agents and
    # service accounts are distinguished by account_type, not a role.
    for rname in ("admin", "member", "viewer"):
        if not db.query(Role).filter(Role.name == rname).first():
            db.add(Role(name=rname))
    db.flush()

    # Statuses
    default_statuses = [("backlog", 0), ("todo", 1), ("in_progress", 2), ("review", 3), ("done", 4)]
    for sname, pos in default_statuses:
        if not db.query(Status).filter(Status.name == sname).first():
            db.add(Status(name=sname, position=pos))
    db.flush()

    # Transition permissions
    transitions = [
        ("backlog", "todo"),
        ("todo", "in_progress"),
        ("in_progress", "review"),
        ("review", "done"),
        ("review", "in_progress"),
        ("in_progress", "backlog"),
        ("todo", "backlog"),
        ("done", "backlog"),
    ]

    for fr, to in transitions:
        codename = f"transition:{fr}:{to}"
        if not db.query(Permission).filter(Permission.codename == codename).first():
            db.add(Permission(codename=codename, description=f"Move {fr} → {to}"))
    db.flush()

    # CRUD + Scope permissions
    for perm in [
        "task.create",
        "task.delete",
        "project.manage",
        "project.view_all",
        "project.write_all",
        "transition:*",
    ]:
        if not db.query(Permission).filter(Permission.codename == perm).first():
            db.add(Permission(codename=perm))
    db.flush()

    # Admin gets all permissions explicitly
    admin = db.query(Role).filter(Role.name == "admin").first()
    for perm in db.query(Permission).all():
        existing = db.query(RolePermission).filter_by(role_id=admin.id, permission_id=perm.id).first()
        if not existing:
            db.add(RolePermission(role_id=admin.id, permission_id=perm.id))

    # Permissions for Members & Bots
    member_perms = [
        "transition:*",
        "task.create", "task.delete",
        # project.manage intentionally omitted (only admins manage projects)
    ]

    for rname in ["member"]:
        role_obj = db.query(Role).filter(Role.name == rname).first()
        if not role_obj: continue
        
        for codename in member_perms:
            perm = db.query(Permission).filter(Permission.codename == codename).first()
            if perm:
                existing = db.query(RolePermission).filter_by(role_id=role_obj.id, permission_id=perm.id).first()
                if not existing:
                    db.add(RolePermission(role_id=role_obj.id, permission_id=perm.id))

    # Viewer gets nothing

    db.commit()


def _ensure_system_org(db: Session) -> Org:
    """The org the bootstrap/seed admin lives in. Stable id so reboots are
    idempotent."""
    # id columns are VARCHAR(12) — keep this id exactly 12 chars.
    org = db.get(Org, "orgsystem000")
    if not org:
        org = Org(id="orgsystem000", name="System Org")
        db.add(org)
        db.flush()
    return org


def bootstrap():
    """Initialize DB tables and seed defaults.

    Privileged throughout: seeding predates any request org-context, and the
    seed admin's profile insert must bypass RLS WITH CHECK."""
    init_db()
    with privileged(), _session() as db:
        _seed_defaults(db)

        # Ensure an admin user exists. AP-194: no hardcoded prod credential.
        # Prod: bootstrap only from AGENTIRA_ADMIN_PASSWORD (fail loud if
        # unset — the operator must choose a real password). Dev: a clearly
        # labelled convenience admin so local setup still works out of the box.
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        if not db.query(Profile).filter(Profile.name == "admin").first():
            is_prod = os.getenv("RAILWAY_ENVIRONMENT") is not None
            admin_password = os.getenv("AGENTIRA_ADMIN_PASSWORD")
            if admin_password:
                sys_org = _ensure_system_org(db)
                db.add(Profile(name="admin", display_name="Admin User",
                               org_id=sys_org.id, account_type="human", roles=[admin_role],
                               password_hash=passwords.hash_password(admin_password)))
                db.commit()
                logger.info("Created admin user from AGENTIRA_ADMIN_PASSWORD")
            elif is_prod:
                logger.error(
                    "No admin user and AGENTIRA_ADMIN_PASSWORD is unset in "
                    "production — set it and restart to bootstrap the admin.")
            else:
                logger.warning("Creating DEV admin user (password: admin123) "
                               "— set AGENTIRA_ADMIN_PASSWORD for real deploys")
                sys_org = _ensure_system_org(db)
                db.add(Profile(name="admin", display_name="Admin User",
                               org_id=sys_org.id, account_type="human", roles=[admin_role],
                               password_hash=passwords.hash_password("admin123")))
                db.commit()

    # AP-157: seed default agents into the system org. Real orgs get their own
    # default agents at creation time via seed_org_defaults().
    try:
        with privileged(), _session() as db:
            sys_org = _ensure_system_org(db)
            db.commit()
            sys_org_id = sys_org.id
        seed_org_defaults(sys_org_id)
    except Exception as exc:  # noqa: BLE001 — never fail bootstrap
        logger.warning("default agent seed failed: %s", exc)
