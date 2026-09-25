"""Typed links between tasks (AP-507).

A link is one relationship seen from two sides: linking A "depends on" B is the
same fact as B "blocks" A, so a single write shows up on both tasks. Hierarchy
links reuse `Task.parent_id` (one source of truth for the tree); every other
type is a row in `task_dependencies` carrying its `link_type`.

Only `depends_on` links gate scheduling — `blocked_by` / `is_blocked` ignore
the rest.
"""

from __future__ import annotations

from backend import services, task_graph
from backend.auth import require_project_access
from backend.models import Task
from backend.repos import task_graph as graph_repo

INVERSE = {
    "depends_on": "blocks",
    "blocks": "depends_on",
    "child_of": "parent_of",
    "parent_of": "child_of",
    "relates_to": "relates_to",
    "duplicates": "duplicated_by",
    "duplicated_by": "duplicates",
}

LINK_TYPES = tuple(INVERSE)
HIERARCHY_TYPES = ("child_of", "parent_of")
# Stored direction per type: the row always reads task_id → depends_on_id.
_STORED = {"depends_on": "depends_on", "relates_to": "relates_to",
           "duplicates": "duplicates"}

GraphError = task_graph.GraphError


def _hierarchy_link_id(child_id: str) -> str:
    return f"parent:{child_id}"


def _link(link_id: str, link_type: str, other: dict) -> dict:
    return {"id": link_id, "type": link_type, "task": other}


def _collect(db, task) -> list[dict]:
    rows = graph_repo.links_for_task(db, task.id)
    children = graph_repo.children_of(db, task.id)
    ids = {r.task_id for r in rows} | {r.depends_on_id for r in rows}
    ids.update(c.id for c in children)
    if task.parent_id:
        ids.add(task.parent_id)
    summaries = graph_repo.task_summaries(db, list(ids))

    out: list[dict] = []
    if task.parent_id and task.parent_id in summaries:
        out.append(_link(_hierarchy_link_id(task.id), "child_of",
                         summaries[task.parent_id]))
    for child in children:
        out.append(_link(_hierarchy_link_id(child.id), "parent_of",
                         summaries[child.id]))
    for row in rows:
        if row.task_id == task.id and row.depends_on_id in summaries:
            out.append(_link(row.id, row.link_type, summaries[row.depends_on_id]))
        elif row.depends_on_id == task.id and row.task_id in summaries:
            out.append(_link(row.id, INVERSE.get(row.link_type, row.link_type),
                             summaries[row.task_id]))
    return out


def list_links(task_id: str, actor: str = "system") -> list[dict]:
    with services._session() as db:
        task = services._resolve_task(db, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        require_project_access(db, actor, task.project_id, "read")
        return _collect(db, task)


def add_link(task_id: str, other_task_id: str, link_type: str,
             actor: str = "system") -> dict:
    """Create (or retype) the link between two tasks, from `task_id`'s side."""
    with services._session() as db:
        task = services._resolve_task(db, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        project_id = task.project_id
        require_project_access(db, actor, project_id, "write")
        if link_type not in INVERSE:
            raise GraphError(f"unknown link type: {link_type}")
        if task.id == other_task_id:
            raise GraphError("a task cannot link to itself")

        other = services._resolve_task(db, other_task_id)
        if not other:
            raise GraphError("task not found")
        if other.project_id != project_id:
            raise GraphError("both tasks must belong to this project")

        if link_type in HIERARCHY_TYPES:
            child, parent = (task, other) if link_type == "child_of" else (other, task)
            task_graph.validate_parent(db, child, parent.id)
            child.parent_id = parent.id
            link_id = _hierarchy_link_id(child.id)
        else:
            forward = link_type in _STORED
            source, target = (task, other) if forward else (other, task)
            stored_type = _STORED[link_type if forward else INVERSE[link_type]]
            if stored_type == graph_repo.DEPENDS_ON:
                edges = graph_repo.edges_for_project(db, project_id)
                if task_graph._reaches(edges, target.id, source.id):
                    raise GraphError("that link would create a cycle")
            graph_repo.delete_edges_between(db, task.id, other.id)
            row = graph_repo.add_edge(db, project_id, source.id, target.id,
                                      creator=actor, link_type=stored_type)
            link_id = row.id

        services._log_activity(
            db, actor, "task.link.add",
            f"{link_type.replace('_', ' ')} {other.key or other.id}",
            project_id=project_id, task_id=task.id)
        db.commit()
        return _link(link_id, link_type,
                     graph_repo.task_summaries(db, [other.id])[other.id])


def remove_link(task_id: str, link_id: str, actor: str = "system") -> bool:
    with services._session() as db:
        task = services._resolve_task(db, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        project_id = task.project_id
        require_project_access(db, actor, project_id, "write")
        if link_id.startswith("parent:"):
            child = db.get(Task, link_id.split(":", 1)[1])
            if not child or child.project_id != project_id:
                return False
            child.parent_id = None
        else:
            row = graph_repo.get_dependency(db, link_id)
            if not row or row.project_id != project_id:
                return False
            graph_repo.delete_edge(db, row)
        services._log_activity(db, actor, "task.link.remove", "Link removed",
                               project_id=project_id, task_id=task.id)
        db.commit()
        return True
