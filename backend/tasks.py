"""Task domain — typed, class-based.

A task can be a plain task, a bug, or other types later. The type is stored on
`Task.type` and selects a `TaskService` (or a subclass when behavior actually
diverges). `services.py` keeps thin wrappers that delegate here, so REST/MCP
callers are untouched.

SQL lives in `backend.forge.repos.tasks`; cross-domain helpers (status, profile,
activity, attachments, notifications) are reused from `services` — this module
composes, it does not own their SQL.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from backend import services
from backend import agent_notifier
from backend.auth import has_permission
from backend.notifications import broker
from backend.models import Task, TaskPriority, Project, ProjectMember, ProjectRepo
from backend.forge.repos import tasks as tasks_repo

# Known task types. Behavior is identical for now (base TaskService); a subclass
# is registered in _OVERRIDES only once a type's behavior actually diverges.
# ponytail: no speculative empty subclasses — the factory is the polymorphism
# seam, subclasses land when bug/feature/etc. need different DoD or status flow.
VALID_TYPES = {"task", "bug"}
_OVERRIDES: dict[str, type["TaskService"]] = {}

# Declarative spec for the scalar fields update() can change. Adding a new
# scalar field = add a row here (+ wire its param into `incoming`), not another
# if-branch. Optional per-field hooks (sensible defaults when absent):
#   coerce(raw)  -> stored value          (default: identity)
#   current(t)   -> value to compare      (default: getattr(task, name))
#   diff(old,new)-> (from_repr, to_repr)  (default: (old, new))
#   label(raw,val)-> activity message     (default: f"{name} → {val}")
# Fields with bespoke storage/validation (tags, dod_items, repos) stay explicit.
_UPDATE_FIELDS = (
    {"name": "title"},
    {"name": "description",
     "diff": lambda o, n: (o[:80], n[:80]),
     "label": lambda raw, val: "description updated"},
    {"name": "priority",
     "coerce": lambda v: TaskPriority(v),
     "current": lambda t: t.priority,
     "diff": lambda o, n: (o.value, n.value),
     "label": lambda raw, val: f"priority → {raw}"},
    {"name": "assignee"},
    {"name": "start_date",
     "coerce": lambda v: _parse_dt(v),
     "diff": lambda o, n: (str(o), str(n)),
     "label": lambda raw, val: f"start_date -> {raw}"},
    {"name": "due_date",
     "coerce": lambda v: _parse_dt(v),
     "diff": lambda o, n: (str(o), str(n)),
     "label": lambda raw, val: f"due_date -> {raw}"},
    {"name": "branch",
     "current": lambda t: t.branch or "",
     "label": lambda raw, val: f"branch → {val}" if val else "branch cleared"},
    {"name": "pr_url",
     "current": lambda t: t.pr_url or "",
     "label": lambda raw, val: "PR linked" if val else "PR unlinked"},
    {"name": "epic_id",
     "coerce": lambda v: v if v.strip() else None,
     "label": lambda raw, val: f"epic_id → {val}"},
)


def resolve(task_type: str = "task") -> "TaskService":
    """Factory: the service for a task type. Unknown types fall back to base."""
    cls = _OVERRIDES.get(task_type, TaskService)
    return cls(task_type if task_type in VALID_TYPES else "task")


def for_task(task: Task) -> "TaskService":
    """The service matching an existing task's stored type."""
    return resolve(task.type or "task")


class TaskService:
    """Base behavior for all task types."""

    def __init__(self, task_type: str = "task"):
        self.task_type = task_type

    # ── create ────────────────────────────────────────────────────────────
    def create(
        self,
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
        with services._session() as db:
            project = db.get(Project, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            if not has_permission(db, actor, "project.view_all"):
                profile = services._get_profile_by_name(db, actor)
                if not profile:
                    raise PermissionError(f"User {actor} not found")
                is_member = db.query(ProjectMember).filter_by(
                    project_id=project_id, profile_id=profile.id
                ).first()
                if not is_member:
                    raise PermissionError(
                        f"User {actor} is not a member of project {project_id}")

            status_id = services._get_status_id(db, status)
            start_dt = _parse_dt(start_date)
            due_dt = _parse_dt(due_date)

            prefix = project.key_prefix or "PROJ"
            num = project.next_task_number or 1
            task_key = f"{prefix}-{num}"
            project.next_task_number = num + 1

            task = Task(
                project_id=project_id,
                key=task_key,
                type=self.task_type,
                title=title,
                description=description,
                status_id=status_id,
                priority=TaskPriority(priority),
                assignee=assignee,
                creator=actor,
                tags=",".join(tags) if tags else "",
                start_date=start_dt,
                due_date=due_dt,
                dod_items=json.dumps(services._normalize_dod(dod_items)) if dod_items else None,
                epic_id=epic_id if epic_id and epic_id.strip() else None,
            )
            db.add(task)
            db.flush()

            services._log_activity(
                db, actor, "task.create", f"Created task: {title}",
                project_id=project_id, task_id=task.id,
                notify_users=[assignee] if assignee and assignee != actor else []
            )
            db.commit()

            if assignee and assignee != actor:
                target_prof = services._get_profile_by_name(db, assignee)
                if target_prof:
                    broker.notify(target_prof.id)
            agent_notifier.dispatch(db, "task.assigned", services._task_to_dict(task), actor)

            db.refresh(task)
            return services._task_to_dict(task, attachments_count=services._attachment_count(db, task.id))

    # ── read ──────────────────────────────────────────────────────────────
    def list(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        priority: Optional[str] = None,
        actor: str = "system",
    ) -> list[dict]:
        with services._session() as db:
            q = db.query(Task)

            if not has_permission(db, actor, "project.view_all"):
                profile = services._get_profile_by_name(db, actor)
                if not profile:
                    return []
                my_project_ids = [
                    pm.project_id for pm in
                    db.query(ProjectMember.project_id).filter(
                        ProjectMember.profile_id == profile.id).all()
                ]
                from sqlalchemy import or_
                q = q.filter(or_(
                    Task.project_id.in_(my_project_ids),
                    Task.assignee == actor,
                ))

            if project_id:
                q = q.filter(Task.project_id == project_id)
            if status:
                q = q.filter(Task.status_id == services._get_status_id(db, status))
            if assignee:
                q = q.filter(Task.assignee == assignee)
            if priority:
                q = q.filter(Task.priority == TaskPriority(priority))

            tasks = q.order_by(Task.updated_at.desc()).all()
            ids = [t.id for t in tasks]
            counts = services._batch_attachment_counts(db, ids)
            active = services._active_run_agents(db, ids)
            out = []
            for t in tasks:
                d = services._task_to_dict(t, attachments_count=counts.get(t.id, 0))
                info = active.get(t.id)
                d["agent_active"] = info is not None
                if info:
                    d["active_agent_id"] = info["agent_id"]
                    d["active_agent_name"] = info["agent_name"]
                out.append(d)
            return out

    def get(self, task_id: str) -> dict | None:
        with services._session() as db:
            t = tasks_repo.resolve_ref(db, task_id)
            if not t:
                return None
            d = services._task_to_dict(t, attachments_count=services._attachment_count(db, t.id))
            info = services._active_run_agents(db, [t.id]).get(t.id)
            d["agent_active"] = info is not None
            if info:
                d["active_agent_id"] = info["agent_id"]
                d["active_agent_name"] = info["agent_name"]
            return d

    # ── update ────────────────────────────────────────────────────────────
    def update(
        self,
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
        actor: str = "system",
    ) -> dict:
        with services._session() as db:
            task = tasks_repo.resolve_ref(db, task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            task_id = task.id

            changes: list[str] = []
            diff: dict = {}
            incoming = {
                "title": title, "description": description, "priority": priority,
                "assignee": assignee, "start_date": start_date, "due_date": due_date,
                "branch": branch, "pr_url": pr_url, "epic_id": epic_id,
            }
            # Data-driven scalar updates — see _UPDATE_FIELDS. A new scalar field
            # is a row there + an entry above, not another branch here.
            for spec in _UPDATE_FIELDS:
                raw = incoming[spec["name"]]
                if raw is None:                      # param not provided
                    continue
                attr = spec["name"]
                val = spec["coerce"](raw) if "coerce" in spec else raw
                cur = spec["current"](task) if "current" in spec else getattr(task, attr)
                if val == cur:
                    continue
                frm, to = spec["diff"](cur, val) if "diff" in spec else (cur, val)
                setattr(task, attr, val)
                diff[attr] = {"from": frm, "to": to}
                changes.append(spec["label"](raw, val) if "label" in spec
                               else f"{attr} → {val}")

            if tags is not None:
                old_tags = task.tags.split(",") if task.tags else []
                if old_tags != tags:
                    diff["tags"] = {"from": old_tags, "to": tags}
                    changes.append(f"tags → {tags}")
                task.tags = ",".join(tags)
            if dod_items is not None:
                old_dod = services._normalize_dod(services._parse_dod(task.dod_items)) or []
                new_dod = services._normalize_dod(dod_items) or []
                task.dod_items = json.dumps(new_dod) if new_dod else None
                old_checked = sum(1 for i in old_dod if i.get("checked"))
                new_checked = sum(1 for i in new_dod if i.get("checked"))
                if old_checked != new_checked or len(old_dod) != len(new_dod):
                    changes.append(f"DOD {new_checked}/{len(new_dod)} checked")
            if repos is not None:
                # AP-154: multi-repo. Normalize, dedupe order-preserving, validate.
                seen = set()
                cleaned: list[str] = []
                for name in repos:
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    cleaned.append(name)
                if cleaned and task.project_id:
                    valid_names = {
                        n[0] for n in db.query(ProjectRepo.name)
                                         .filter(ProjectRepo.project_id == task.project_id)
                                         .all()
                    }
                    if valid_names:
                        bad = [n for n in cleaned if n not in valid_names]
                        if bad:
                            raise ValueError(f"repo(s) {bad} not declared on project")
                new_repos_json = json.dumps(cleaned) if cleaned else None
                if new_repos_json != task.repos_json:
                    diff["repos"] = {"from": services.resolve_task_repos(task), "to": cleaned}
                    task.repos_json = new_repos_json
                    task.repo_name = cleaned[0] if cleaned else None
                    changes.append(f"repos → {cleaned}")

            if changes:
                services._log_activity(
                    db, actor, "task.update", "; ".join(changes),
                    project_id=task.project_id, task_id=task_id,
                    diff=json.dumps(diff) if diff else None,
                    notify_users=[task.assignee] if task.assignee and task.assignee != actor else []
                )

            db.commit()
            if assignee and assignee != actor:
                target_prof = services._get_profile_by_name(db, assignee)
                if target_prof:
                    broker.notify(target_prof.id)
            agent_notifier.dispatch(db, "task.updated", services._task_to_dict(task), actor)

            db.refresh(task)
            return services._task_to_dict(task, attachments_count=services._attachment_count(db, task.id))

    # ── move ──────────────────────────────────────────────────────────────
    def move(self, task_id: str, new_status: str, actor: str = "system") -> dict:
        from backend.auth import check_transition

        with services._session() as db:
            task = tasks_repo.resolve_ref(db, task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            task_id = task.id

            old = task.status.name
            if old == new_status:
                return services._task_to_dict(task, attachments_count=services._attachment_count(db, task.id))

            check_transition(db, actor, old, new_status)

            # AP-158: per-project column-exit gates (opt-in via gates_enabled).
            if task.project and getattr(task.project, "gates_enabled", False):
                from backend import gates as _gates
                _gates.enforce(task, from_status=old, to_status=new_status)

            task.status_id = services._get_status_id(db, new_status)

            services._log_activity(
                db, actor, "task.move", f"{old} → {new_status}",
                project_id=task.project_id, task_id=task_id,
                diff=json.dumps({"status": {"from": old, "to": new_status}}),
                notify_users=[task.assignee] if task.assignee and task.assignee != actor else []
            )

            db.commit()
            if task.assignee and task.assignee != actor:
                target_prof = services._get_profile_by_name(db, task.assignee)
                if target_prof:
                    broker.notify(target_prof.id)
            agent_notifier.dispatch(db, "task.moved", services._task_to_dict(task), actor)

            db.refresh(task)
            return services._task_to_dict(task, attachments_count=services._attachment_count(db, task.id))

    # ── delete ────────────────────────────────────────────────────────────
    def delete(self, task_id: str) -> bool:
        with services._session() as db:
            task = tasks_repo.resolve_ref(db, task_id)
            if not task:
                return False
            tasks_repo.delete_with_children(db, task)
            db.commit()
            return True


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
