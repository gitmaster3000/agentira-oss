"""Task graph domain (AP-496): child tasks, task dependencies, milestones.

Three small features that share one invariant — the work graph must stay a
DAG. A cycle (task A waits on B waits on A, or a subtask that is its own
grandparent) has no valid schedule, so every write here proves acyclicity
before it commits.

Composition only: SQL lives in `backend.repos.task_graph`, auth in
`backend.auth`, dates/serialization reused from `backend.services`.
"""

from __future__ import annotations

from datetime import datetime

from backend import services
from backend.auth import require_project_access
from backend.models import Task
from backend.repos import task_graph as graph_repo

MAX_DEPTH = 50


class GraphError(ValueError):
    """Invalid graph mutation — surfaced to callers as HTTP 400."""


# ── serialization ────────────────────────────────────────────────────────

def _dep_to_dict(dep) -> dict:
    return {
        "id": dep.id,
        "project_id": dep.project_id,
        "task_id": dep.task_id,
        "depends_on_id": dep.depends_on_id,
        "creator": dep.creator or "",
        "created_at": dep.created_at.isoformat() if dep.created_at else None,
    }


def _milestone_to_dict(ms, counts: dict | None = None) -> dict:
    counts = counts or {"total": 0, "done": 0}
    total, done = counts.get("total", 0), counts.get("done", 0)
    return {
        "id": ms.id,
        "project_id": ms.project_id,
        "title": ms.title,
        "description": ms.description or "",
        "due_date": ms.due_date.isoformat() if ms.due_date else None,
        "status": ms.status,
        "color": ms.color,
        "creator": ms.creator or "",
        "created_at": ms.created_at.isoformat() if ms.created_at else None,
        "total": total,
        "done": done,
        "progress": round(done / total * 100) if total else 0,
    }


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GraphError(f"invalid date: {value!r}") from exc


# ── child tasks ──────────────────────────────────────────────────────────

def validate_parent(db, task: Task, parent_id: str) -> None:
    """Raise GraphError unless `task` may be parented under `parent_id`."""
    if parent_id == task.id:
        raise GraphError("a task cannot be its own parent")
    parent = db.get(Task, parent_id)
    if not parent:
        raise GraphError(f"parent task {parent_id} not found")
    if parent.project_id != task.project_id:
        raise GraphError("parent task must be in the same project")
    # Walking up from the proposed parent must never reach `task` itself.
    if task.id in graph_repo.ancestor_ids(db, parent_id, limit=MAX_DEPTH):
        raise GraphError("that parent would create a cycle in the task tree")


def list_subtasks(task_id: str, actor: str = "system") -> list[dict]:
    with services._session() as db:
        task = services._resolve_task(db, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        require_project_access(db, actor, task.project_id, "read")
        children = graph_repo.children_of(db, task.id)
        counts = graph_repo.subtask_counts(db, [c.id for c in children])
        out = []
        for child in children:
            d = services._task_to_dict(child)
            d["subtasks"] = counts.get(child.id, {"total": 0, "done": 0})
            out.append(d)
        return out


# ── dependencies ─────────────────────────────────────────────────────────

def _reaches(edges: list[tuple[str, str]], start: str, target: str) -> bool:
    """Is `target` reachable from `start` following task → depends_on edges?"""
    adjacency: dict[str, list[str]] = {}
    for task_id, depends_on_id in edges:
        adjacency.setdefault(task_id, []).append(depends_on_id)
    stack, seen = [start], {start}
    while stack:
        node = stack.pop()
        if node == target:
            return True
        for nxt in adjacency.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def list_dependencies(project_id: str, actor: str = "system") -> list[dict]:
    with services._session() as db:
        require_project_access(db, actor, project_id, "read")
        return [_dep_to_dict(d) for d in graph_repo.list_dependencies(db, project_id)]


def add_dependency(project_id: str, task_id: str, depends_on_id: str,
                   actor: str = "system") -> dict:
    """`task_id` waits on `depends_on_id`. Idempotent: re-adding an existing
    edge returns it instead of erroring."""
    with services._session() as db:
        require_project_access(db, actor, project_id, "write")
        if task_id == depends_on_id:
            raise GraphError("a task cannot depend on itself")

        task = services._resolve_task(db, task_id)
        blocker = services._resolve_task(db, depends_on_id)
        if not task or not blocker:
            raise GraphError("task not found")
        if task.project_id != project_id or blocker.project_id != project_id:
            raise GraphError("both tasks must belong to this project")

        existing = graph_repo.find_edge(db, task.id, blocker.id)
        if existing:
            return _dep_to_dict(existing)

        edges = graph_repo.edges_for_project(db, project_id)
        # The new edge is task → blocker; a cycle exists iff blocker already
        # reaches task through the current graph.
        if _reaches(edges, blocker.id, task.id):
            raise GraphError("that dependency would create a cycle")

        dep = graph_repo.add_edge(db, project_id, task.id, blocker.id, creator=actor)
        services._log_activity(
            db, actor, "task.dependency.add",
            f"Depends on {blocker.key or blocker.id}",
            project_id=project_id, task_id=task.id)
        db.commit()
        db.refresh(dep)
        return _dep_to_dict(dep)


def remove_dependency(project_id: str, dep_id: str, actor: str = "system") -> bool:
    with services._session() as db:
        require_project_access(db, actor, project_id, "write")
        dep = graph_repo.get_dependency(db, dep_id)
        if not dep or dep.project_id != project_id:
            return False
        task_id = dep.task_id
        graph_repo.delete_edge(db, dep)
        services._log_activity(db, actor, "task.dependency.remove",
                               "Dependency removed",
                               project_id=project_id, task_id=task_id)
        db.commit()
        return True


def annotate_blocking(db, task_dicts: list[dict]) -> None:
    """Add `blocked_by`, `blocks` and `is_blocked` to already-serialized tasks.

    In place, batched — callers pass the whole board/list at once. A task is
    blocked when at least one thing it depends on isn't done yet.
    """
    ids = [d["id"] for d in task_dicts]
    neighbors = graph_repo.neighbor_tasks(db, ids)
    for d in task_dicts:
        info = neighbors.get(d["id"], {})
        blocked_by = info.get("blocked_by", [])
        d["blocked_by"] = blocked_by
        d["blocks"] = info.get("blocks", [])
        d["is_blocked"] = any(
            b["status"] != graph_repo.DONE_STATUS for b in blocked_by)


# ── milestones ───────────────────────────────────────────────────────────

def list_milestones(project_id: str, actor: str = "system") -> list[dict]:
    with services._session() as db:
        require_project_access(db, actor, project_id, "read")
        rows = graph_repo.list_milestones(db, project_id)
        counts = graph_repo.milestone_counts(db, [m.id for m in rows])
        return [_milestone_to_dict(m, counts.get(m.id)) for m in rows]


def create_milestone(project_id: str, title: str, description: str = "",
                     due_date: str | None = None, color: str = "#2ecc71",
                     actor: str = "system") -> dict:
    with services._session() as db:
        require_project_access(db, actor, project_id, "write")
        clean_title = (title or "").strip()
        if not clean_title:
            raise GraphError("milestone title is required")
        ms = graph_repo.add_milestone(
            db, project_id, clean_title, description=description or "",
            due_date=_parse_date(due_date), color=color or "#2ecc71",
            creator=actor)
        services._log_activity(db, actor, "milestone.create",
                               f"Created milestone: {clean_title}",
                               project_id=project_id)
        db.commit()
        db.refresh(ms)
        return _milestone_to_dict(ms)


def update_milestone(project_id: str, milestone_id: str, title: str | None = None,
                     description: str | None = None, due_date: str | None = None,
                     status: str | None = None, color: str | None = None,
                     actor: str = "system") -> dict:
    with services._session() as db:
        require_project_access(db, actor, project_id, "write")
        ms = graph_repo.get_milestone(db, milestone_id)
        if not ms or ms.project_id != project_id:
            raise ValueError(f"Milestone {milestone_id} not found")
        if title is not None:
            clean_title = title.strip()
            if not clean_title:
                raise GraphError("milestone title is required")
            ms.title = clean_title
        if description is not None:
            ms.description = description
        if due_date is not None:
            ms.due_date = _parse_date(due_date)
        if status is not None:
            if status not in ("planned", "achieved", "missed"):
                raise GraphError(f"invalid milestone status: {status}")
            ms.status = status
        if color is not None:
            ms.color = color
        services._log_activity(db, actor, "milestone.update",
                               f"Updated milestone: {ms.title}",
                               project_id=project_id)
        db.commit()
        db.refresh(ms)
        counts = graph_repo.milestone_counts(db, [ms.id])
        return _milestone_to_dict(ms, counts.get(ms.id))


def delete_milestone(project_id: str, milestone_id: str,
                     actor: str = "system") -> bool:
    with services._session() as db:
        require_project_access(db, actor, project_id, "write")
        ms = graph_repo.get_milestone(db, milestone_id)
        if not ms or ms.project_id != project_id:
            return False
        title = ms.title
        graph_repo.delete_milestone(db, ms)
        services._log_activity(db, actor, "milestone.delete",
                               f"Deleted milestone: {title}",
                               project_id=project_id)
        db.commit()
        return True


def validate_milestone(db, task: Task, milestone_id: str) -> None:
    ms = graph_repo.get_milestone(db, milestone_id)
    if not ms or ms.project_id != task.project_id:
        raise GraphError("milestone must belong to the same project")


# ── task lifecycle hooks ─────────────────────────────────────────────────

def on_task_deleted(db, task_id: str) -> None:
    """Called from TaskService.delete before the row goes: drop dependency
    edges pointing either way, and orphan (not delete) the children."""
    graph_repo.delete_edges_for_task(db, task_id)
    graph_repo.detach_children(db, task_id)


def set_parent(db, task: Task, parent_id: str | None) -> str | None:
    """Validate + apply a parent change. Returns the stored value."""
    value = (parent_id or "").strip() or None
    if value:
        validate_parent(db, task, value)
    task.parent_id = value
    return value
