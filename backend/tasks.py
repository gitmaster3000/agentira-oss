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
import logging
from datetime import datetime
from typing import Optional

from backend import services
from backend import agent_notifier
from backend import task_graph
from backend.auth import project_ids_for_actor, require_project_access
from backend.notifications import broker
from backend.models import Task, TaskPriority, Project, ProjectMember, ProjectRepo, Profile, allow_task_write
from backend.forge.repos import tasks as tasks_repo
from backend.forge.repos import transitions as transitions_repo
from backend.repos import tasks as core_tasks_repo
from backend.repos import task_graph as core_graph_repo

logger = logging.getLogger("agentira.tasks")

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


def _is_project_member(db, project_id: str, profile_name: str) -> bool:
    """True if the named profile belongs to the project — either the
    human-facing ProjectMember join row, or (for agents, per
    backend.forge.workflow.pick_role_agent) a matching
    Profile.default_project_id."""
    prof = db.query(Profile).filter(Profile.name == profile_name).first()
    if not prof:
        return False
    if prof.default_project_id == project_id:
        return True
    return db.query(ProjectMember).filter_by(
        project_id=project_id, profile_id=prof.id).first() is not None


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
        parent_id: str | None = None,
        milestone_id: str | None = None,
    ) -> dict:
        with services._session() as db:
            project = db.get(Project, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            require_project_access(db, actor, project_id, "write")

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

            # AP-496: let a caller create a task already nested under a parent
            # or already counted towards a milestone — agents plan that way.
            if parent_id:
                task_graph.set_parent(db, task, parent_id)
            if milestone_id and milestone_id.strip():
                task_graph.validate_milestone(db, task, milestone_id.strip())
                task.milestone_id = milestone_id.strip()

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
            q = core_tasks_repo.with_list_relations(db.query(Task))

            project_ids = project_ids_for_actor(db, actor)
            if project_ids is not None:
                q = q.filter(Task.project_id.in_(project_ids))

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
            commit_counts = core_tasks_repo.batch_commit_counts(db, ids)
            active = services._active_run_agents(db, ids)
            out = []
            for t in tasks:
                d = services._task_to_dict(t, attachments_count=counts.get(t.id, 0),
                                            commits_count=commit_counts.get(t.id, 0))
                info = active.get(t.id)
                d["agent_active"] = info is not None
                if info:
                    d["active_agent_id"] = info["agent_id"]
                    d["active_agent_name"] = info["agent_name"]
                out.append(d)
            # AP-496: subtask rollup + blocked-by, batched over the whole list.
            sub_counts = core_graph_repo.subtask_counts(db, ids)
            for d in out:
                d["subtasks"] = sub_counts.get(d["id"], {"total": 0, "done": 0})
            task_graph.annotate_blocking(db, out)
            return out

    def get(self, task_id: str, actor: str = "system") -> dict | None:
        with services._session() as db:
            t = tasks_repo.resolve_ref(db, task_id)
            if not t:
                return None
            require_project_access(db, actor, t.project_id, "read")
            d = services._task_to_dict(t, attachments_count=services._attachment_count(db, t.id))
            d["subtasks"] = core_graph_repo.subtask_counts(db, [t.id]).get(
                t.id, {"total": 0, "done": 0})
            task_graph.annotate_blocking(db, [d])
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
        parent_id: Optional[str] = None,
        milestone_id: Optional[str] = None,
        actor: str = "system",
    ) -> dict:
        with services._session() as db:
            task = tasks_repo.resolve_ref(db, task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            task_id = task.id
            require_project_access(db, actor, task.project_id, "write")

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
                # AP-374: an automated hand-off (the workflow driver) may only
                # assign to a current project member — this is exactly the
                # channel that let a non-member agent take a task over the
                # ORM-write bypass. Human/admin reassignment via the API
                # keeps its existing, more permissive behavior (ad-hoc
                # cross-project assignment is an intentional escape hatch —
                # see test_list_tasks_scoping).
                if attr == "assignee" and actor == "workflow" and val:
                    if not _is_project_member(db, task.project_id, val):
                        raise PermissionError(
                            f"workflow cannot assign task {task_id} to "
                            f"'{val}': not a member of project {task.project_id}"
                        )
                cur = spec["current"](task) if "current" in spec else getattr(task, attr)
                if val == cur:
                    continue
                frm, to = spec["diff"](cur, val) if "diff" in spec else (cur, val)
                with allow_task_write():
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

            # AP-496: graph pointers. Both validate against the task graph
            # (same project, no cycles) before they touch the row; "" detaches.
            if parent_id is not None:
                new_parent = task_graph.set_parent(db, task, parent_id)
                changes.append(f"parent → {new_parent or 'none'}")
            if milestone_id is not None:
                new_milestone = milestone_id.strip() or None
                if new_milestone:
                    task_graph.validate_milestone(db, task, new_milestone)
                task.milestone_id = new_milestone
                changes.append(f"milestone → {new_milestone or 'none'}")

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
    def move(self, task_id: str, new_status: str, actor: str = "system",
             skip_gates: bool = False, record_transition: bool = True) -> dict:
        from backend.auth import check_transition

        with services._session() as db:
            task = tasks_repo.resolve_ref(db, task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            task_id = task.id
            require_project_access(db, actor, task.project_id, "write")

            old = task.status.name
            if old == new_status:
                return services._task_to_dict(task, attachments_count=services._attachment_count(db, task.id))

            check_transition(db, actor, old, new_status)

            # AP-158: per-project column-exit gates (opt-in via gates_enabled).
            # skip_gates is an explicit, visible escape hatch for the workflow
            # driver's two-phase `integrate` advance: it already verified
            # stronger evidence (a real merge, daemon-confirmed) than the
            # pr_url/branch proxy gates check, and re-running them here would
            # be a spurious re-entrant failure, not a real block.
            if not skip_gates and task.project and getattr(task.project, "gates_enabled", False):
                from backend import gates as _gates
                import time as _time
                started = _time.monotonic()
                results = _gates.evaluate(task, from_status=old, to_status=new_status)
                failed = _gates.failures(results)
                transitions_repo.record_gate_evaluation(
                    db, task_id=task_id, from_status=old, to_status=new_status,
                    gate_id=f"{old}:{new_status}",
                    evidence_snapshot=_gate_evidence_snapshot(task),
                    outcome="block" if failed else "allow",
                    reason="; ".join(f.reason for f in failed),
                    duration_ms=int((_time.monotonic() - started) * 1000),
                )
                db.commit()
                if failed:
                    raise _gates.GateFailure(old, new_status, failed)

            with allow_task_write():
                task.status_id = services._get_status_id(db, new_status)

            services._log_activity(
                db, actor, "task.move", f"{old} → {new_status}",
                project_id=task.project_id, task_id=task_id,
                diff=json.dumps({"status": {"from": old, "to": new_status}}),
                notify_users=[task.assignee] if task.assignee and task.assignee != actor else []
            )
            if record_transition:
                transitions_repo.record_transition(
                    db, task_id=task_id, from_status=old, to_status=new_status,
                    actor_type=_actor_type(db, actor), actor_id=actor,
                    cause="move", result="allowed",
                )

            db.commit()
            if task.assignee and task.assignee != actor:
                target_prof = services._get_profile_by_name(db, task.assignee)
                if target_prof:
                    broker.notify(target_prof.id)
            agent_notifier.dispatch(db, "task.moved", services._task_to_dict(task), actor)

            db.refresh(task)
            result = services._task_to_dict(task, attachments_count=services._attachment_count(db, task.id))

        # A human moving a task starts that column's agent with its workflow
        # prompt (policy in the workflow config; no-op otherwise).
        if old != new_status:
            from backend.forge import workflow as _workflow
            _workflow.dispatch_on_manual_move(task_id, new_status, actor)

        # AP-190: a completed task compacts each agent's conversation so a later
        # reopen starts from a summary, not the whole transcript. Best-effort —
        # the move must succeed regardless. Done outside the session above.
        if new_status == "done":
            try:
                from backend.forge import compaction
                compaction.compact_task_on_done(task_id)
            except Exception as exc:  # noqa: BLE001 — never fail a move on this
                logger.warning("compaction on done failed task=%s: %s",
                               task_id, exc)
        return result

    # ── delete ────────────────────────────────────────────────────────────
    def delete(self, task_id: str, actor: str = "system") -> bool:
        with services._session() as db:
            task = tasks_repo.resolve_ref(db, task_id)
            if not task:
                return False
            require_project_access(db, actor, task.project_id, "write")
            # AP-496: drop dependency edges and orphan child tasks first —
            # both reference this row and neither should die with it.
            task_graph.on_task_deleted(db, task.id)
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


def _gate_evidence_snapshot(task: Task) -> dict:
    """The task field values the AP-158 local gates read — captured at
    evaluation time so a block/allow is explainable after the task's fields
    have since changed."""
    return {
        "dod_items": task.dod_items,
        "assignee": task.assignee,
        "branch": task.branch,
        "pr_url": task.pr_url,
    }


def _actor_type(db, actor: str) -> str:
    """Best-effort classification for transition_events.actor_type, from
    the profile's stored account_type (human / agentira_agent /
    external_agent) — falls back to "workflow" for the driver's own actor
    strings, "system" when no profile resolves."""
    if actor in ("system", "workflow"):
        return actor
    profile = services._get_profile_by_name(db, actor)
    if not profile:
        return "system"
    return "human" if profile.account_type == "human" else "agent"
