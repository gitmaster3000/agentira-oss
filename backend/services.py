"""Facade service — all business logic lives here.

Both REST API and MCP server call into this layer.
"""

from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session

from backend.db import SessionLocal, init_db
from backend.models import (
    Project, Task, Activity, TaskPriority, Profile, Attachment,
    Role, Permission, RolePermission, ProfilePermission, Status,
    ProjectMember, Notification, TaskCommit, Epic, OAuthAccount
)
from backend.auth import has_permission
from backend.notifications import broker
from backend import agent_notifier

import logging
import os
import hashlib
import secrets

logger = logging.getLogger("agentira.services")

def _hash_password(password: str) -> str:
    """Simple SHA-256 hash for basic auth."""
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate_user(username: str, password: str) -> dict | None:
    """Verify credentials and return profile dict."""
    with _session() as db:
        p = db.query(Profile).filter(Profile.name == username).first()
        if not p:
            return None
        if p.password_hash == _hash_password(password):
            return _profile_to_dict(p)
    return None

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


def _dod_progress(dod: list | None) -> dict | None:
    if not dod:
        return None
    total = len(dod)
    checked = sum(1 for item in dod if item.get("checked"))
    return {"total": total, "checked": checked}


def _resolve_task(db: Session, task_ref: str) -> Task | None:
    """Resolve a task by ID or Jira-style key (e.g. 'AGNT-1')."""
    task = db.get(Task, task_ref)
    if task:
        return task
    return db.query(Task).filter(Task.key == task_ref.upper()).first()


def _task_to_dict(t: Task, attachments_count: int = 0) -> dict:
    dod = _parse_dod(t.dod_items)
    return {
        "id": t.id,
        "key": t.key or t.id,
        "project_id": t.project_id,
        "epic_id": t.epic_id,
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
        "commits_count": len(t.commits) if t.commits else 0,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
        "attachments_count": attachments_count,
    }


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


def _project_to_dict(p: Project) -> dict:
    return {
        "id": p.id,
        "key_prefix": p.key_prefix or "PROJ",
        "name": p.name,
        "description": p.description,
        "repo_path": p.repo_path or "",
        "conventions_md": p.conventions_md or "",
        # ADR 009 / AP-136: run-crystallization work-signal mode ("" = default).
        "work_signal": getattr(p, "work_signal", None) or "",
        "created_at": p.created_at.isoformat(),
        "task_count": len(p.tasks),
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
    role_name = p.role.name
    # Derived identity kind. Three values:
    #   user            — role=user
    #   managed_agent   — role=bot AND runtime_id IS NOT NULL
    #   service_account — role=bot AND runtime_id IS NULL
    if role_name == "bot":
        kind = "managed_agent" if p.runtime_id else "service_account"
    else:
        kind = "user"
    return {
        "id": p.id,
        "name": p.name,
        "display_name": p.display_name or p.name,
        "role": role_name,
        "kind": kind,
        "email": p.email,
        "avatar_url": p.avatar_url,
        "webhook_url": p.webhook_url,
        "extra_permissions": extra,
        "projects": [pm.project_id for pm in p.project_memberships],
        "runtime_id": p.runtime_id,
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


def list_notifications(profile_id: str, unread_only: bool = True) -> list[dict]:
    with _session() as db:
        q = db.query(Notification).filter(Notification.profile_id == profile_id)
        if unread_only:
            q = q.filter(Notification.read == False)
        notifs = q.order_by(Notification.created_at.desc()).all()
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


def create_project(name: str, description: str = "", actor: str = "system") -> dict:
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

    # ── Kickoff: auto-add the Conductor + create the first task ──────────
    # Conductor is the workspace orchestrator (backend/forge/conductor.py).
    # Every new project starts with it as a member and one "Plan this
    # project" task already assigned and ready to Run — the user just
    # attaches the design + clicks Run, and the Conductor produces the
    # plan as an artifact + spawns the concrete child tasks.
    # Best-effort: if the Conductor isn't seedable in this workspace
    # (missing 'bot' role on a fresh install) we still return the project.
    try:
        _seed_project_kickoff(project_id=project_id, actor=actor)
    except Exception as exc:  # noqa: BLE001 — project must still be created
        logger.warning("project kickoff seeding failed project=%s: %s",
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
    with _session() as db:
        if has_permission(db, actor, "project.view_all"):
            projects = db.query(Project).order_by(Project.created_at.desc()).all()
        else:
            profile = _get_profile_by_name(db, actor)
            if not profile:
                return []
            projects = (
                db.query(Project)
                .join(ProjectMember)
                .filter(ProjectMember.profile_id == profile.id)
                .order_by(Project.created_at.desc())
                .all()
            )
        return [_project_to_dict(p) for p in projects]


def get_project(project_id: str) -> dict | None:
    with _session() as db:
        p = db.get(Project, project_id)
        return _project_to_dict(p) if p else None


def update_project(project_id: str, name: Optional[str] = None, description: Optional[str] = None,
                   repo_path: Optional[str] = None, conventions_md: Optional[str] = None,
                   work_signal: Optional[str] = None) -> dict:
    with _session() as db:
        p = db.get(Project, project_id)
        if not p:
            raise ValueError(f"Project {project_id} not found")
        if name is not None:
            p.name = name
        if description is not None:
            p.description = description
        if repo_path is not None:
            p.repo_path = repo_path
        if conventions_md is not None:
            p.conventions_md = conventions_md
        if work_signal is not None:
            # ADR 009: validate against the known modes; ignore junk.
            from backend.forge.turns import WORK_SIGNAL_MODES
            if work_signal in WORK_SIGNAL_MODES:
                p.work_signal = work_signal
        db.commit()
        db.refresh(p)
        return _project_to_dict(p)


def delete_project(project_id: str) -> bool:
    with _session() as db:
        p = db.get(Project, project_id)
        if not p:
            return False
        db.delete(p)
        db.commit()
        return True


def add_project_member(project_id: str, profile_name: str, actor: str = "system") -> dict:
    """Add a user to a project."""
    with _session() as db:
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


def list_project_members(project_id: str) -> list[dict]:
    """Return all members of a project as profile dicts."""
    with _session() as db:
        p = db.get(Project, project_id)
        if not p:
            return []
        members = db.query(ProjectMember).filter_by(project_id=p.id).all()
        return [_profile_to_dict(pm.profile) for pm in members]


def remove_project_member(project_id: str, profile_name: str) -> bool:
    """Remove a user from a project and clear their task assignments."""
    with _session() as db:
        p = db.get(Project, project_id)
        prof = _get_profile_by_name(db, profile_name)
        if not p or not prof:
            return False

        pm = db.query(ProjectMember).filter_by(project_id=p.id, profile_id=prof.id).first()
        if not pm:
            return False
        
        # Clear assignments for this user in this project
        tasks = db.query(Task).filter_by(project_id=p.id, assignee=profile_name).all()
        for t in tasks:
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

def _epic_to_dict(e: Epic) -> dict:
    return {
        "id": e.id,
        "project_id": e.project_id,
        "title": e.title,
        "description": e.description,
        "status": e.status,
        "assignee": e.assignee,
        "creator": e.creator,
        "color": e.color,
        "task_count": len(e.tasks),
        "created_at": e.created_at.isoformat(),
    }

def create_epic(project_id: str, title: str, description: str = "", color: str = "#7c4dff", actor: str = "system") -> dict:
    with _session() as db:
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

        if not has_permission(db, actor, "project.view_all"):
            profile = _get_profile_by_name(db, actor)
            if not profile:
                return []
            my_project_ids = [
                pm.project_id for pm in 
                db.query(ProjectMember.project_id).filter(ProjectMember.profile_id == profile.id).all()
            ]
            q = q.filter(Epic.project_id.in_(my_project_ids))

        if project_id:
            q = q.filter(Epic.project_id == project_id)

        epics = q.order_by(Epic.created_at.desc()).all()
        return [_epic_to_dict(e) for e in epics]

def get_epic(epic_id: str) -> dict | None:
    """Single-epic fetch — returns the dict or None if not found."""
    with _session() as db:
        epic = db.get(Epic, epic_id)
        return _epic_to_dict(epic) if epic else None


def list_epic_tasks(epic_id: str) -> list[dict]:
    """All tasks linked to this epic, newest first."""
    with _session() as db:
        epic = db.get(Epic, epic_id)
        if not epic:
            return []
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

def delete_epic(epic_id: str) -> bool:
    with _session() as db:
        epic = db.get(Epic, epic_id)
        if not epic:
            return False
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
) -> dict:
    """Create a task. Enforces membership check (unless admin/wildcard)."""
    with _session() as db:
        project = db.get(Project, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Check membership logic
        if not has_permission(db, actor, "project.view_all"):
            profile = _get_profile_by_name(db, actor)
            if not profile:
                raise PermissionError(f"User {actor} not found")
            
            is_member = db.query(ProjectMember).filter_by(
                project_id=project_id, profile_id=profile.id
            ).first()
            if not is_member:
                raise PermissionError(f"User {actor} is not a member of project {project_id}")

        import json
        status_id = _get_status_id(db, status)
        from datetime import datetime
        start_dt = None
        if start_date:
            try: start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            except ValueError: pass
        due_dt = None
        if due_date:
            try: due_dt = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
            except ValueError: pass

        # Generate Jira-style key
        prefix = project.key_prefix or "PROJ"
        num = project.next_task_number or 1
        task_key = f"{prefix}-{num}"
        project.next_task_number = num + 1

        task = Task(
            project_id=project_id,
            key=task_key,
            title=title,
            description=description,
            status_id=status_id,
            priority=TaskPriority(priority),
            assignee=assignee,
            creator=actor,
            tags=",".join(tags) if tags else "",
            start_date=start_dt,
            due_date=due_dt,
            dod_items=json.dumps(dod_items) if dod_items else None,
            epic_id=epic_id if epic_id and epic_id.strip() else None,
        )
        db.add(task)
        db.flush()

        _log_activity(
            db, actor, "task.create", f"Created task: {title}",
            project_id=project_id, task_id=task.id,
            notify_users=[assignee] if assignee and assignee != actor else []
        )
        db.commit()
        
        if assignee and assignee != actor:
            target_prof = _get_profile_by_name(db, assignee)
            if target_prof:
                broker.notify(target_prof.id)
        agent_notifier.dispatch(db, "task.assigned", _task_to_dict(task), actor)

        db.refresh(task)
        return _task_to_dict(task, attachments_count=_attachment_count(db, task.id))


def list_tasks(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    priority: Optional[str] = None,
    actor: str = "system",
) -> list[dict]:
    """List tasks scoped by visibility.

    - Admin / 'project.view_all': Sees all tasks matching filters.
    - Others: Sees tasks from their projects OR assigned to them.
    """
    with _session() as db:
        q = db.query(Task)
        
        # Apply scoping rules
        if not has_permission(db, actor, "project.view_all"):
            profile = _get_profile_by_name(db, actor)
            if not profile:
                # Unknown actor sees nothing unless it's system (which has wildcard perms)
                # But here has_permission already handled system/wildcard.
                return []
            
            # Subquery based approach or simple IN clause
            my_project_ids = [
                pm.project_id for pm in 
                db.query(ProjectMember.project_id).filter(ProjectMember.profile_id == profile.id).all()
            ]
            
            # Condition: Task in my projects OR Task assigned to me
            from sqlalchemy import or_
            q = q.filter(
                or_(
                    Task.project_id.in_(my_project_ids),
                    Task.assignee == actor
                )
            )

        # Filters
        if project_id:
            q = q.filter(Task.project_id == project_id)
        if status:
            sid = _get_status_id(db, status)
            q = q.filter(Task.status_id == sid)
        if assignee:
            q = q.filter(Task.assignee == assignee)
        if priority:
            q = q.filter(Task.priority == TaskPriority(priority))
            
        tasks = q.order_by(Task.updated_at.desc()).all()
        counts = _batch_attachment_counts(db, [t.id for t in tasks])
        return [_task_to_dict(t, attachments_count=counts.get(t.id, 0)) for t in tasks]


def get_task(task_id: str) -> dict | None:
    with _session() as db:
        t = _resolve_task(db, task_id)
        if not t:
            return None
        return _task_to_dict(t, attachments_count=_attachment_count(db, t.id))


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
    actor: str = "system",
) -> dict:
    with _session() as db:
        task = _resolve_task(db, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        task_id = task.id

        import json
        changes = []
        diff = {}
        if title is not None and title != task.title:
            diff["title"] = {"from": task.title, "to": title}
            task.title = title
            changes.append(f"title → {title}")
        if description is not None and description != task.description:
            diff["description"] = {"from": task.description[:80], "to": description[:80]}
            task.description = description
            changes.append("description updated")
        if priority is not None and priority != task.priority.value:
            diff["priority"] = {"from": task.priority.value, "to": priority}
            task.priority = TaskPriority(priority)
            changes.append(f"priority → {priority}")
        if assignee is not None and assignee != task.assignee:
            diff["assignee"] = {"from": task.assignee, "to": assignee}
            task.assignee = assignee
            changes.append(f"assignee → {assignee}")
        if start_date is not None:
            from datetime import datetime
            dt = None
            try: dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            except ValueError: pass
            if dt != task.start_date:
                diff["start_date"] = {"from": str(task.start_date), "to": str(dt)}
                task.start_date = dt
                changes.append(f"start_date -> {start_date}")

        if due_date is not None:
            from datetime import datetime
            dt = None
            try: dt = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
            except ValueError: pass
            if dt != task.due_date:
                diff["due_date"] = {"from": str(task.due_date), "to": str(dt)}
                task.due_date = dt
                changes.append(f"due_date -> {due_date}")

        if tags is not None:
            old_tags = task.tags.split(",") if task.tags else []
            if old_tags != tags:
                diff["tags"] = {"from": old_tags, "to": tags}
                changes.append(f"tags → {tags}")
            task.tags = ",".join(tags)

        if dod_items is not None:
            old_dod = _parse_dod(task.dod_items) or []
            task.dod_items = json.dumps(dod_items)
            old_checked = sum(1 for i in old_dod if i.get("checked"))
            new_checked = sum(1 for i in dod_items if i.get("checked"))
            if old_checked != new_checked or len(old_dod) != len(dod_items):
                changes.append(f"DOD {new_checked}/{len(dod_items)} checked")

        if branch is not None and branch != (task.branch or ""):
            diff["branch"] = {"from": task.branch or "", "to": branch}
            task.branch = branch
            changes.append(f"branch → {branch}" if branch else "branch cleared")
        if pr_url is not None and pr_url != (task.pr_url or ""):
            diff["pr_url"] = {"from": task.pr_url or "", "to": pr_url}
            task.pr_url = pr_url
            changes.append(f"PR linked" if pr_url else "PR unlinked")

        if epic_id is not None:
            new_epic_id = epic_id if epic_id.strip() else None
            if task.epic_id != new_epic_id:
                diff["epic_id"] = {"from": task.epic_id, "to": new_epic_id}
                task.epic_id = new_epic_id
                changes.append(f"epic_id → {new_epic_id}")

        if changes:
            _log_activity(
                db, actor, "task.update", "; ".join(changes),
                project_id=task.project_id, task_id=task_id,
                diff=json.dumps(diff) if diff else None,
                notify_users=[task.assignee] if task.assignee and task.assignee != actor else []
            )

        db.commit()
        if assignee and assignee != actor:
            target_prof = _get_profile_by_name(db, assignee)
            if target_prof:
                broker.notify(target_prof.id)
        agent_notifier.dispatch(db, "task.updated", _task_to_dict(task), actor)

        db.refresh(task)
        return _task_to_dict(task, attachments_count=_attachment_count(db, task.id))


def move_task(task_id: str, new_status: str, actor: str = "system") -> dict:
    from backend.auth import check_transition

    with _session() as db:
        task = _resolve_task(db, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        task_id = task.id

        old = task.status.name
        if old == new_status:
            return _task_to_dict(task, attachments_count=_attachment_count(db, task.id))

        check_transition(db, actor, old, new_status)

        new_status_id = _get_status_id(db, new_status)
        task.status_id = new_status_id
        
        import json
        _log_activity(
            db, actor, "task.move", f"{old} → {new_status}",
            project_id=task.project_id, task_id=task_id,
            diff=json.dumps({"status": {"from": old, "to": new_status}}),
            notify_users=[task.assignee] if task.assignee and task.assignee != actor else []
        )
        
        db.commit()
        if task.assignee and task.assignee != actor:
            target_prof = _get_profile_by_name(db, task.assignee)
            if target_prof:
                broker.notify(target_prof.id)
        agent_notifier.dispatch(db, "task.moved", _task_to_dict(task), actor)

        db.refresh(task)
        return _task_to_dict(task, attachments_count=_attachment_count(db, task.id))


def delete_task(task_id: str) -> bool:
    with _session() as db:
        task = _resolve_task(db, task_id)
        if not task:
            return False
        db.delete(task)
        db.commit()
        return True


# ── Activity / comments ─────────────────────────────────────────────────

def add_comment(task_id: str, comment: str, actor: str = "system") -> dict:
    with _session() as db:
        task = _resolve_task(db, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        task_id = task.id

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

    # Wake the assigned agent — comment lands in its task chat and triggers
    # the ADR 009 D routing (running -> pause+steer, paused/parked -> resume,
    # terminal -> fresh turn). Best-effort, never fails the comment write.
    # Skip if the actor IS the assignee (avoids an agent's own comment
    # re-dispatching itself).
    if task.assignee and task.assignee != actor:
        try:
            _wake_assigned_agent_on_comment(
                task_id=task_id, assignee_name=task.assignee,
                actor=actor, comment=comment,
            )
        except Exception as exc:  # noqa: BLE001 — comment must succeed regardless
            logger.warning("wake-on-comment failed task=%s: %s", task_id, exc)

    return result


def _wake_assigned_agent_on_comment(*, task_id: str, assignee_name: str,
                                    actor: str, comment: str) -> None:
    """Comment -> assigned agent's task chat + dispatch (ADR 009 D).

    Find the Forge agent whose profile.name == assignee_name; if it has a
    bound runtime, deliver the comment as a USER message into the task
    scope via send_runtime_message — which auto-routes per the run state
    (running pauses+steers, paused resumes, idle/terminal starts a turn).
    Skips silently for non-agent assignees (humans) or agents without a
    runtime (purely HTTP-executor agents).
    """
    from backend.forge.models import Agent as ForgeAgent
    from backend.forge import services as forge_services
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
    forge_services.send_runtime_message(
        agent_id,
        content=f"[Comment from {actor}] {comment}",
        scope_key=f"task:{task_id}",
    )


def get_activity(task_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
    with _session() as db:
        activities = (
            db.query(Activity)
            .filter(Activity.task_id == task_id)
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
        "is_primary": bool(r.is_primary),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def list_project_repos(project_id: str) -> list[dict]:
    """AP-121: enumerate repos attached to a project."""
    from backend.models import ProjectRepo
    with _session() as db:
        rows = (db.query(ProjectRepo)
                  .filter(ProjectRepo.project_id == project_id)
                  .order_by(ProjectRepo.is_primary.desc(),
                            ProjectRepo.created_at.asc())
                  .all())
        return [_project_repo_to_dict(r) for r in rows]


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
    if not (repo_path or repo_url):
        return {"error": "repo_path or repo_url is required"}
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


def get_project_activity(project_id: str, limit: int = 50) -> list[dict]:
    """Return recent activity across all tasks in a project, newest first."""
    with _session() as db:
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

        statuses = db.query(Status).order_by(Status.position).all()
        board: dict[str, list[dict]] = {s.name: [] for s in statuses}

        tasks = db.query(Task).filter(Task.project_id == project_id).order_by(Task.updated_at.desc()).all()
        counts = _batch_attachment_counts(db, [t.id for t in tasks])
        for t in tasks:
            board[t.status.name].append(_task_to_dict(t, attachments_count=counts.get(t.id, 0)))

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

        tasks = db.query(Task).filter(Task.project_id == project_id).order_by(Task.created_at.asc()).all()

        STATUS_PROGRESS = {"done": 100, "review": 75, "in_progress": 50, "todo": 25, "backlog": 0}

        # Group by epic or tag. For epic grouping we also remember the
        # epic id + color per group so the UI can link to the epic page.
        groups: dict[str, list] = {}
        group_meta: dict[str, dict] = {}
        milestones = []
        all_dates = []

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
            }

            groups.setdefault(group_key, []).append(task_data)
            all_dates.append(start)
            if end:
                all_dates.append(end)

            # Completed tasks = milestones
            if status_name == "done":
                milestones.append({
                    "id": t.id,
                    "title": t.title,
                    "date": t.updated_at.isoformat(),
                    "epic": group_key,
                })

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

        return {
            "project": {"id": project.id, "name": project.name},
            "epics": group_list,
            "milestones": sorted(milestones, key=lambda m: m["date"], reverse=True)[:10],
            "summary": {
                "total_tasks": sum(e["total"] for e in group_list),
                "total_done": sum(e["done"] for e in group_list),
                "total_epics": len(group_list),
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


def add_attachment(task_id: str, filename: str, file_bytes: bytes, content_type: str = "application/octet-stream", uploaded_by: str = "system") -> dict:
    return _attachments.add(
        task_id=task_id, filename=filename, file_bytes=file_bytes,
        content_type=content_type, uploaded_by=uploaded_by,
    )


def list_attachments(task_id: str) -> list[dict]:
    return _attachments.list_for_task(task_id)


def get_attachment(attachment_id: str) -> tuple[dict, str] | None:
    return _attachments.get(attachment_id)


def get_attachment_bytes(attachment_id: str) -> tuple[dict, bytes] | None:
    return _attachments.get_bytes(attachment_id)


def delete_attachment(attachment_id: str) -> bool:
    return _attachments.delete(attachment_id)


# ── Profile operations ──────────────────────────────────────────────────

def validate_api_key(api_key: str) -> dict:
    """Validate API key and return profile dict. Use this for MCP authentication."""
    if not api_key:
        raise ValueError("API key required")
    with _session() as db:
        p = db.query(Profile).filter(Profile.api_key == api_key).first()
        if not p:
            raise ValueError("Invalid API key")
        return _profile_to_dict(p)


def create_profile(name: str, display_name: str = "", role: str = "member", avatar_url: str = "", password: str = "") -> dict:
    """Internal use. Returns profile dict WITH api_key."""
    with _session() as db:
        role_id = _get_role_id(db, role)
        password_hash = _hash_password(password) if password else ""
        profile = Profile(
            name=name, 
            display_name=display_name or name, 
            role_id=role_id, 
            avatar_url=avatar_url,
            password_hash=password_hash,
            api_key=secrets.token_hex(32)
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        res = _profile_to_dict(profile)
        res["api_key"] = profile.api_key  # Include key only on creation
        return res


def create_service_account(name: str, display_name: str = "", role: str = "bot") -> dict:
    """Create a service account (bot) profile and return its API key."""
    # Ensure name is unique or append suffix? For now, let DB constraint handle it.
    if not display_name:
        display_name = name
    
    # Force role to be bot if not specified (though arg default is bot)
    return create_profile(name, display_name, role=role)


def signup(name: str, display_name: str = "", password: str = "") -> dict:
    """Public signup procedure. Defaults to 'member' role. Returns profile + api_key."""
    return create_profile(name, display_name, role="member", password=password)


def authenticate_oauth(provider: str, provider_user_id: str, email: str | None = None,
                       display_name: str = "", avatar_url: str = "") -> dict:
    """Log in or auto-register a user via OAuth provider.

    Looks up OAuthAccount by (provider, provider_user_id).
    If found → return existing profile.
    If not → create a new profile and link the OAuth account.
    """
    with _session() as db:
        # Check for existing OAuth link
        link = (db.query(OAuthAccount)
                .filter(OAuthAccount.provider == provider,
                        OAuthAccount.provider_user_id == provider_user_id)
                .first())
        if link:
            profile = db.query(Profile).get(link.profile_id)
            return _profile_to_dict(profile)

        # Check if a profile with this email already exists (link it)
        profile = None
        if email:
            profile = db.query(Profile).filter(Profile.email == email).first()

        if not profile:
            # Create new profile
            role_id = _get_role_id(db, "member")
            # Generate a unique username from email or display name
            base_name = (email.split("@")[0] if email else display_name.lower().replace(" ", "_"))[:60]
            name = base_name
            suffix = 1
            while db.query(Profile).filter(Profile.name == name).first():
                name = f"{base_name}_{suffix}"
                suffix += 1

            profile = Profile(
                name=name,
                display_name=display_name or name,
                email=email,
                role_id=role_id,
                avatar_url=avatar_url,
                api_key=secrets.token_hex(32),
            )
            db.add(profile)
            db.flush()

        # Create OAuth link
        db.add(OAuthAccount(
            profile_id=profile.id,
            provider=provider,
            provider_user_id=provider_user_id,
        ))
        db.commit()
        db.refresh(profile)
        return _profile_to_dict(profile)


def list_profiles(role: Optional[str] = None) -> list[dict]:
    with _session() as db:
        q = db.query(Profile)
        if role:
            q = q.join(Role).filter(Role.name == role)
        return [_profile_to_dict(p) for p in q.order_by(Profile.name).all()]


def list_service_accounts() -> list[dict]:
    """Service accounts: bot-role profiles WITHOUT a runtime binding.

    These are API-key-only identities used by external systems (CI, plugins,
    external MCP/Claude sessions). They're project-membership-capable but
    NOT dispatched by Forge — Forge agents live in `forge_agents` with a
    non-null `runtime_id` and are surfaced by `forge.services.list_agents`.
    """
    from sqlalchemy import or_
    with _session() as db:
        q = (db.query(Profile)
               .join(Role).filter(Role.name == "bot")
               # Defensive: data may have empty-string runtime_id from older
               # rows; treat either NULL or "" as "no runtime".
               .filter(or_(Profile.runtime_id.is_(None), Profile.runtime_id == "")))
        return [_profile_to_dict(p) for p in q.order_by(Profile.name).all()]


def get_profile(profile_id: str) -> dict | None:
    with _session() as db:
        p = db.get(Profile, profile_id)
        return _profile_to_dict(p) if p else None


def get_service_account(profile_id: str) -> dict | None:
    """Returns bot profile details WITH api_key."""
    with _session() as db:
        p = db.get(Profile, profile_id)
        if not p or p.role.name != "bot":
            return None
        res = _profile_to_dict(p)
        res["api_key"] = p.api_key
        return res


def update_profile(profile_id: str, display_name: Optional[str] = None, role: Optional[str] = None, avatar_url: Optional[str] = None, webhook_url: Optional[str] = None) -> dict:
    with _session() as db:
        p = db.get(Profile, profile_id)
        if not p:
            raise ValueError(f"Profile {profile_id} not found")
        
        # TODO: Add actor check here if not already handled by caller (REST/MCP)
        # For now, we assume caller validates permissions.
        
        if display_name is not None:
            p.display_name = display_name
        if role is not None:
            # Only admin should change role, but again, caller check.
            p.role_id = _get_role_id(db, role)
        if avatar_url is not None:
            p.avatar_url = avatar_url
        if webhook_url is not None:
            p.webhook_url = webhook_url
            
        db.commit()
        db.refresh(p)
        return _profile_to_dict(p)


def delete_profile(profile_id: str) -> bool:
    with _session() as db:
        p = db.get(Profile, profile_id)
        if not p:
            return False
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
        existing = db.query(TaskCommit).filter_by(task_id=task_id, pr_number=pr_number, kind="pr").first()
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

    # Roles
    for rname in ("admin", "member", "viewer", "bot"):
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
    for perm in ["task.create", "task.delete", "project.manage", "project.view_all", "transition:*"]:
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

    for rname in ["member", "bot"]:
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


def bootstrap():
    """Initialize DB tables and seed defaults."""
    init_db()
    with _session() as db:
        _seed_defaults(db)
        
        # Ensure admin user exists with password
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        if not db.query(Profile).filter(Profile.name == "admin").first():
            print("Creating default admin user (password: admin123)")
            p = Profile(
                name="admin", 
                display_name="Admin User", 
                role_id=admin_role.id,
                password_hash=_hash_password("admin123")
            )
            db.add(p)
            db.commit()
