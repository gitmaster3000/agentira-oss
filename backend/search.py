"""Global search across projects, tasks, epics and agents (top-bar search)."""
from __future__ import annotations

from backend import services
from backend.auth import project_ids_for_actor
from backend.repos import search as search_repo

PER_GROUP_LIMIT = 5


def search(q: str, actor: str, limit: int = PER_GROUP_LIMIT) -> dict:
    q = (q or "").strip()
    out = {"projects": [], "tasks": [], "epics": [], "agents": []}
    if not q:
        return out
    with services._session() as db:
        ids = project_ids_for_actor(db, actor)
        if ids is not None and not ids:
            return out
        projects = search_repo.search_projects(db, q, ids, limit)
        tasks = search_repo.search_tasks(db, q, ids, limit)
        epics = search_repo.search_epics(db, q, ids, limit)
        agents = search_repo.search_agents(db, q, limit)
        names = search_repo.project_names(
            db, {x.project_id for x in [*tasks, *epics]})
        names.update({p.id: p.name for p in projects})
        out["projects"] = [{"id": p.id, "name": p.name, "key": p.key_prefix} for p in projects]
        out["tasks"] = [{"id": t.id, "key": t.key, "title": t.title, "status": t.status.name if t.status else "",
                         "project_id": t.project_id, "project_name": names.get(t.project_id, "")} for t in tasks]
        out["epics"] = [{"id": e.id, "title": e.title, "project_id": e.project_id,
                         "project_name": names.get(e.project_id, "")} for e in epics]
        out["agents"] = [{"id": a.id, "name": a.name, "model": a.model} for a in agents]
    return out
