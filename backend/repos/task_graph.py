"""Data access for the task graph (AP-496): child tasks, dependency edges
and roadmap milestones.

Services compose, repos own the SQL (CLAUDE.md). Every function takes an open
session — this module never opens its own. Counts are batched by design: the
board, backlog and roadmap all render N tasks at once, so a per-row lazy load
here is an N+1 on the hottest read paths in the product.
"""
from __future__ import annotations

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import selectinload

from backend.models import Milestone, Status, Task, TaskDependency

DONE_STATUS = "done"
DEPENDS_ON = "depends_on"


# ── child tasks ──────────────────────────────────────────────────────────

def children_of(db, parent_id: str) -> list[Task]:
    return (
        db.query(Task)
        .options(selectinload(Task.status), selectinload(Task.epic))
        .filter(Task.parent_id == parent_id)
        .order_by(Task.created_at.asc())
        .all()
    )


def subtask_counts(db, parent_ids: list[str]) -> dict[str, dict]:
    """{parent_id: {"total": n, "done": n}} in one grouped query."""
    if not parent_ids:
        return {}
    rows = (
        db.query(Task.parent_id, Status.name, func.count(Task.id))
        .join(Status, Task.status_id == Status.id)
        .filter(Task.parent_id.in_(parent_ids))
        .group_by(Task.parent_id, Status.name)
        .all()
    )
    out: dict[str, dict] = {}
    for parent_id, status_name, count in rows:
        bucket = out.setdefault(parent_id, {"total": 0, "done": 0})
        bucket["total"] += count
        if status_name == DONE_STATUS:
            bucket["done"] += count
    return out


def ancestor_ids(db, task_id: str, limit: int = 50) -> list[str]:
    """Walk `parent_id` upward. `limit` bounds the walk so a pre-existing
    cycle in the data can never hang a request."""
    seen: list[str] = []
    current = db.query(Task.parent_id).filter(Task.id == task_id).scalar()
    while current and current not in seen and len(seen) < limit:
        seen.append(current)
        current = db.query(Task.parent_id).filter(Task.id == current).scalar()
    return seen


def detach_children(db, task_id: str) -> None:
    """Children outlive their parent — clear the pointer instead of cascading
    the delete (a subtask usually still needs doing)."""
    db.query(Task).filter(Task.parent_id == task_id).update(
        {Task.parent_id: None}, synchronize_session=False)


# ── dependency edges ─────────────────────────────────────────────────────

def list_dependencies(db, project_id: str) -> list[TaskDependency]:
    """Blocking edges only — other link types never gate scheduling."""
    return (
        db.query(TaskDependency)
        .filter(TaskDependency.project_id == project_id,
                TaskDependency.link_type == DEPENDS_ON)
        .order_by(TaskDependency.created_at.asc())
        .all()
    )


def links_for_task(db, task_id: str) -> list[TaskDependency]:
    return (
        db.query(TaskDependency)
        .filter(or_(TaskDependency.task_id == task_id,
                    TaskDependency.depends_on_id == task_id))
        .order_by(TaskDependency.created_at.asc())
        .all()
    )


def get_dependency(db, dep_id: str) -> TaskDependency | None:
    return db.get(TaskDependency, dep_id)


def find_edge(db, task_id: str, depends_on_id: str,
              link_type: str | None = None) -> TaskDependency | None:
    q = db.query(TaskDependency).filter(
        TaskDependency.task_id == task_id,
        TaskDependency.depends_on_id == depends_on_id)
    if link_type is not None:
        q = q.filter(TaskDependency.link_type == link_type)
    return q.first()


def add_edge(db, project_id: str, task_id: str, depends_on_id: str,
             creator: str = "", link_type: str = DEPENDS_ON) -> TaskDependency:
    dep = TaskDependency(project_id=project_id, task_id=task_id,
                         depends_on_id=depends_on_id, creator=creator,
                         link_type=link_type)
    db.add(dep)
    db.flush()
    return dep


def delete_edge(db, dep: TaskDependency) -> None:
    db.delete(dep)


def delete_edges_for_task(db, task_id: str) -> None:
    db.query(TaskDependency).filter(
        or_(TaskDependency.task_id == task_id,
            TaskDependency.depends_on_id == task_id)
    ).delete(synchronize_session=False)


def edges_for_project(db, project_id: str) -> list[tuple[str, str]]:
    """[(task_id, depends_on_id)] — the raw adjacency used for cycle checks."""
    return [
        (task_id, depends_on_id)
        for task_id, depends_on_id in db.query(
            TaskDependency.task_id, TaskDependency.depends_on_id
        ).filter(TaskDependency.project_id == project_id,
                 TaskDependency.link_type == DEPENDS_ON).all()
    ]


def task_summaries(db, task_ids: list[str]) -> dict[str, dict]:
    """{task_id: {id, key, title, status}} — the chip payload the UI renders."""
    if not task_ids:
        return {}
    rows = (
        db.query(Task.id, Task.key, Task.title, Status.name)
        .join(Status, Task.status_id == Status.id)
        .filter(Task.id.in_(task_ids))
        .all()
    )
    return {
        tid: {"id": tid, "key": key or tid, "title": title, "status": status}
        for tid, key, title, status in rows
    }


def delete_edges_between(db, task_id: str, other_id: str) -> None:
    db.query(TaskDependency).filter(
        or_(and_(TaskDependency.task_id == task_id,
                 TaskDependency.depends_on_id == other_id),
            and_(TaskDependency.task_id == other_id,
                 TaskDependency.depends_on_id == task_id))
    ).delete(synchronize_session=False)


def neighbor_tasks(db, task_ids: list[str]) -> dict[str, dict]:
    """{task_id: {"blocked_by": [...], "blocks": [...]}} for the given tasks.

    Two queries total (edges + the referenced tasks), so a board of N tasks
    costs the same as one.
    """
    if not task_ids:
        return {}
    edges = (
        db.query(TaskDependency.task_id, TaskDependency.depends_on_id)
        .filter(TaskDependency.link_type == DEPENDS_ON,
                or_(TaskDependency.task_id.in_(task_ids),
                    TaskDependency.depends_on_id.in_(task_ids)))
        .all()
    )
    if not edges:
        return {}
    referenced = {tid for pair in edges for tid in pair}
    rows = (
        db.query(Task.id, Task.key, Task.title, Status.name)
        .join(Status, Task.status_id == Status.id)
        .filter(Task.id.in_(referenced))
        .all()
    )
    summary = {
        tid: {"id": tid, "key": key or tid, "title": title, "status": status}
        for tid, key, title, status in rows
    }
    out: dict[str, dict] = {}
    for task_id, depends_on_id in edges:
        if task_id in task_ids and depends_on_id in summary:
            out.setdefault(task_id, {"blocked_by": [], "blocks": []})
            out[task_id]["blocked_by"].append(summary[depends_on_id])
        if depends_on_id in task_ids and task_id in summary:
            out.setdefault(depends_on_id, {"blocked_by": [], "blocks": []})
            out[depends_on_id]["blocks"].append(summary[task_id])
    return out


# ── milestones ───────────────────────────────────────────────────────────

def list_milestones(db, project_id: str) -> list[Milestone]:
    return (
        db.query(Milestone)
        .filter(Milestone.project_id == project_id)
        .order_by(Milestone.due_date.asc().nullslast(), Milestone.created_at.asc())
        .all()
    )


def get_milestone(db, milestone_id: str) -> Milestone | None:
    return db.get(Milestone, milestone_id)


def add_milestone(db, project_id: str, title: str, description: str = "",
                  due_date=None, color: str = "#2ecc71",
                  creator: str = "") -> Milestone:
    ms = Milestone(project_id=project_id, title=title, description=description,
                   due_date=due_date, color=color, creator=creator)
    db.add(ms)
    db.flush()
    return ms


def delete_milestone(db, ms: Milestone) -> None:
    """Unlink tasks first — a milestone is a label on work, deleting it must
    never delete the work."""
    db.query(Task).filter(Task.milestone_id == ms.id).update(
        {Task.milestone_id: None}, synchronize_session=False)
    db.delete(ms)


def milestone_counts(db, milestone_ids: list[str]) -> dict[str, dict]:
    """{milestone_id: {"total": n, "done": n}} in one grouped query."""
    if not milestone_ids:
        return {}
    rows = (
        db.query(Task.milestone_id, Status.name, func.count(Task.id))
        .join(Status, Task.status_id == Status.id)
        .filter(Task.milestone_id.in_(milestone_ids))
        .group_by(Task.milestone_id, Status.name)
        .all()
    )
    out: dict[str, dict] = {}
    for ms_id, status_name, count in rows:
        bucket = out.setdefault(ms_id, {"total": 0, "done": 0})
        bucket["total"] += count
        if status_name == DONE_STATUS:
            bucket["done"] += count
    return out
