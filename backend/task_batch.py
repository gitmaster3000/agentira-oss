"""Batch task creation: land a whole plan (tasks + dependency edges) atomically.

Each entry carries a caller-chosen `ref`; `depends_on_refs` points at other refs
in the same batch. The whole payload is validated (refs, cycles) before anything
is written, and every write shares one transaction — any failure rolls back all
tasks, edges and key numbers.
"""

from __future__ import annotations

from backend import agent_notifier, services, tasks
from backend.notifications import broker
from backend.repos import task_graph as graph_repo
from backend.task_graph import GraphError

MAX_BATCH = 200
_TASK_FIELDS = {
    "title", "description", "status", "priority", "assignee", "tags",
    "start_date", "due_date", "dod_items", "epic_id", "parent_id",
    "milestone_id", "type",
}
_ENTRY_FIELDS = _TASK_FIELDS | {"ref", "depends_on_refs"}


def _validate(entries: list[dict]) -> dict[str, list[str]]:
    """Check shape, refs and acyclicity. Returns {ref: [unique dependency refs]}."""
    if not entries:
        raise GraphError("tasks must not be empty")
    if len(entries) > MAX_BATCH:
        raise GraphError(f"at most {MAX_BATCH} tasks per batch")

    deps: dict[str, list[str]] = {}
    for i, entry in enumerate(entries):
        unknown = set(entry) - _ENTRY_FIELDS
        if unknown:
            raise GraphError(f"tasks[{i}]: unknown field(s) {sorted(unknown)}")
        ref = entry.get("ref")
        if not isinstance(ref, str) or not ref.strip():
            raise GraphError(f"tasks[{i}]: ref is required")
        if ref in deps:
            raise GraphError(f"duplicate ref {ref!r}")
        if not (entry.get("title") or "").strip():
            raise GraphError(f"tasks[{i}] ({ref}): title is required")
        deps[ref] = list(dict.fromkeys(entry.get("depends_on_refs") or []))

    for ref, wanted in deps.items():
        for dep in wanted:
            if dep == ref:
                raise GraphError(f"task {ref!r} cannot depend on itself")
            if dep not in deps:
                raise GraphError(f"task {ref!r} depends on unknown ref {dep!r}")

    # Kahn's algorithm: anything left after peeling off dependency-free tasks
    # sits on (or behind) a cycle.
    remaining = {ref: set(wanted) for ref, wanted in deps.items()}
    ready = [ref for ref, wanted in remaining.items() if not wanted]
    while ready:
        done = ready.pop()
        del remaining[done]
        for ref, wanted in remaining.items():
            if done in wanted:
                wanted.discard(done)
                if not wanted:
                    ready.append(ref)
    if remaining:
        raise GraphError(
            f"dependencies form a cycle among: {', '.join(sorted(remaining))}")
    return deps


def create_tasks(project_id: str, entries: list[dict], actor: str = "system") -> list[dict]:
    """Create every task and dependency edge in one transaction.

    Returns [{ref, id, key}] in input order. Raises GraphError (nothing written)
    for a bad payload; ValueError from field validation also rolls everything back.
    """
    deps = _validate(entries)
    with services._session() as db:
        by_ref = {}
        for entry in entries:
            fields = {k: v for k, v in entry.items() if k in _TASK_FIELDS}
            service = tasks.resolve(fields.pop("type", None) or "task")
            by_ref[entry["ref"]] = service.add(
                db, project_id, actor=actor, **fields)

        for ref, wanted in deps.items():
            task = by_ref[ref]
            for dep_ref in wanted:
                blocker = by_ref[dep_ref]
                graph_repo.add_edge(db, project_id, task.id, blocker.id, creator=actor)
                services._log_activity(
                    db, actor, "task.dependency.add",
                    f"Depends on {blocker.key or blocker.id}",
                    project_id=project_id, task_id=task.id)
        db.commit()

        for entry in entries:
            task = by_ref[entry["ref"]]
            assignee = entry.get("assignee")
            if assignee and assignee != actor:
                prof = services._get_profile_by_name(db, assignee)
                if prof:
                    broker.notify(prof.id)
            agent_notifier.dispatch(db, "task.assigned", services._task_to_dict(task), actor)

        return [{"ref": e["ref"], "id": by_ref[e["ref"]].id, "key": by_ref[e["ref"]].key}
                for e in entries]
