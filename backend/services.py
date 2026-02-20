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
    ProjectMember, Notification
)
from backend.auth import has_permission
from backend.notifications import broker

import os
import hashlib
import secrets

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

ATTACHMENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "attachments")


# ── Helpers ──────────────────────────────────────────────────────────────

def _session() -> Session:
    return SessionLocal()


def _task_to_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "project_id": t.project_id,
        "title": t.title,
        "description": t.description,
        "status": t.status.name,
        "priority": t.priority.value,
        "assignee": t.assignee,
        "tags": [tag.strip() for tag in t.tags.split(",") if tag.strip()] if t.tags else [],
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


def _project_to_dict(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
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
    return {
        "id": p.id,
        "name": p.name,
        "display_name": p.display_name or p.name,
        "role": p.role.name,
        "avatar_url": p.avatar_url,
        "extra_permissions": extra,
        "projects": [pm.project_id for pm in p.project_memberships],
        "created_at": p.created_at.isoformat(),
    }


def _attachment_to_dict(a: Attachment) -> dict:
    return {
        "id": a.id,
        "task_id": a.task_id,
        "filename": a.filename,
        "content_type": a.content_type,
        "size_bytes": a.size_bytes,
        "uploaded_by": a.uploaded_by,
        "created_at": a.created_at.isoformat(),
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

def create_project(name: str, description: str = "", actor: str = "system") -> dict:
    with _session() as db:
        project = Project(name=name, description=description)
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
        return _project_to_dict(project)


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


def update_project(project_id: str, name: Optional[str] = None, description: Optional[str] = None) -> dict:
    with _session() as db:
        p = db.get(Project, project_id)
        if not p:
            raise ValueError(f"Project {project_id} not found")
        if name is not None:
            p.name = name
        if description is not None:
            p.description = description
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


# ── Task operations ─────────────────────────────────────────────────────

def create_task(
    project_id: str,
    title: str,
    description: str = "",
    status: str = "backlog",
    priority: str = "medium",
    assignee: str = "",
    tags: list[str] | None = None,
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

        status_id = _get_status_id(db, status)
        task = Task(
            project_id=project_id,
            title=title,
            description=description,
            status_id=status_id,
            priority=TaskPriority(priority),
            assignee=assignee,
            tags=",".join(tags) if tags else "",
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

        db.refresh(task)
        return _task_to_dict(task)


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
        return [_task_to_dict(t) for t in tasks]


def get_task(task_id: str) -> dict | None:
    with _session() as db:
        t = db.get(Task, task_id)
        return _task_to_dict(t) if t else None


def update_task(
    task_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    assignee: Optional[str] = None,
    tags: Optional[list[str]] = None,
    actor: str = "system",
) -> dict:
    with _session() as db:
        task = db.get(Task, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

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
        if tags is not None:
            old_tags = task.tags.split(",") if task.tags else []
            if old_tags != tags:
                diff["tags"] = {"from": old_tags, "to": tags}
                changes.append(f"tags → {tags}")
            task.tags = ",".join(tags)

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

        db.refresh(task)
        return _task_to_dict(task)


def move_task(task_id: str, new_status: str, actor: str = "system") -> dict:
    from backend.auth import check_transition

    with _session() as db:
        task = db.get(Task, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        old = task.status.name
        if old == new_status:
            return _task_to_dict(task)

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

        db.refresh(task)
        return _task_to_dict(task)


def delete_task(task_id: str) -> bool:
    with _session() as db:
        task = db.get(Task, task_id)
        if not task:
            return False
        db.delete(task)
        db.commit()
        return True


# ── Activity / comments ─────────────────────────────────────────────────

def add_comment(task_id: str, comment: str, actor: str = "system") -> dict:
    with _session() as db:
        task = db.get(Task, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
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

        db.refresh(act)
        return _activity_to_dict(act)


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
            "task": _task_to_dict(task),
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
        for t in tasks:
            board[t.status.name].append(_task_to_dict(t))

        return {
            "project": _project_to_dict(project),
            "columns": board,
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

def add_attachment(task_id: str, filename: str, file_bytes: bytes, content_type: str = "application/octet-stream", uploaded_by: str = "system") -> dict:
    with _session() as db:
        task = db.get(Task, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        task_dir = os.path.join(ATTACHMENTS_DIR, task_id)
        os.makedirs(task_dir, exist_ok=True)

        import uuid
        safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        file_path = os.path.join(task_dir, safe_name)

        with open(file_path, "wb") as f:
            f.write(file_bytes)

        att = Attachment(
            task_id=task_id, filename=filename, content_type=content_type,
            file_path=file_path, size_bytes=len(file_bytes), uploaded_by=uploaded_by,
        )
        db.add(att)

        activity = Activity(task_id=task_id, actor=uploaded_by, action="attached", detail=f"Attached: {filename}")
        db.add(activity)
        db.commit()
        db.refresh(att)
        return _attachment_to_dict(att)


def list_attachments(task_id: str) -> list[dict]:
    with _session() as db:
        atts = db.query(Attachment).filter(Attachment.task_id == task_id).order_by(Attachment.created_at.desc()).all()
        return [_attachment_to_dict(a) for a in atts]


def get_attachment(attachment_id: str) -> tuple[dict, str] | None:
    with _session() as db:
        a = db.get(Attachment, attachment_id)
        if not a:
            return None
        return _attachment_to_dict(a), a.file_path


def delete_attachment(attachment_id: str) -> bool:
    with _session() as db:
        a = db.get(Attachment, attachment_id)
        if not a:
            return False
        if os.path.exists(a.file_path):
            os.remove(a.file_path)
        db.delete(a)
        db.commit()
        return True


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


def list_profiles(role: Optional[str] = None) -> list[dict]:
    with _session() as db:
        q = db.query(Profile)
        if role:
            q = q.join(Role).filter(Role.name == role)
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


def update_profile(profile_id: str, display_name: Optional[str] = None, role: Optional[str] = None, avatar_url: Optional[str] = None) -> dict:
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
