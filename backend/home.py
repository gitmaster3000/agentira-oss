"""Home page API: GET /api/home returns everything Home renders in one
response; GET/PUT /api/home/layout store the user's tile layout."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import services
from backend.jwt_auth import get_current_user
from backend.repos import home as repo

router = APIRouter(prefix="/api/home", tags=["home"], dependencies=[Depends(get_current_user)])


class LayoutBody(BaseModel):
    layout: list[tuple[str, str]] = Field(max_length=50)


def _profile(db, actor: str):
    prof = services._get_profile_by_name(db, actor)
    if not prof:
        raise HTTPException(404, "Profile not found")
    return prof


def build_home(db, prof) -> dict:
    now = datetime.now(timezone.utc)
    projects = repo.member_projects(db, prof.id)
    ids = [p.id for p in projects]
    stats = repo.task_stats_by_project(db, ids, now) if ids else {}
    trend = repo.done_trend_by_project(db, ids, now) if ids else {}
    members = repo.members_by_project(db, ids) if ids else {}
    names = sorted({m.name for ms in members.values() for m in ms})
    people = repo.people_stats(db, ids, names, now) if ids else {}
    feed = repo.recent_task_events(db, ids) if ids else []

    zero = dict.fromkeys(("total", "done", "open", "due_week", "late", "done_week"), 0)
    out_projects = []
    for p in projects:
        s = {**zero, "last_updated": None, **stats.get(p.id, {})}
        ms = members.get(p.id, [])
        out_projects.append({
            "id": p.id, "name": p.name, "key": p.key_prefix,
            "colour": repo.project_colour(p.id), "description": p.description,
            "pct_done": round(100 * s["done"] / s["total"]) if s["total"] else 0,
            "open": s["open"], "due_this_week": s["due_week"], "late": s["late"],
            "members": [{"id": m.id, "name": m.name, "display_name": m.display_name,
                         "avatar_url": m.avatar_url} for m in ms[:repo.AVATAR_LIMIT]],
            "member_count": len(ms),
            "last_updated": s["last_updated"].isoformat() if s["last_updated"] else None,
            "done_per_week": trend.get(p.id, [0] * repo.TREND_WEEKS),
        })
    tot = lambda k: sum(stats.get(i, zero)[k] for i in ids)  # noqa: E731
    return {
        "week": {"done": tot("done_week"), "due": tot("due_week"),
                 "late": tot("late"), "planned": tot("total")},
        "projects": out_projects,
        "activity": feed,
        "people": [{"name": n, "open": people.get(n, {}).get("open", 0),
                    "days_done_this_week": people.get(n, {}).get("days_done_this_week", 0)}
                   for n in names],
        "week_summary": prof.home_week_summary,
    }


@router.get("")
def api_home(actor: str = Depends(get_current_user)):
    with services._session() as db:
        return build_home(db, _profile(db, actor))


@router.get("/layout")
def api_get_layout(actor: str = Depends(get_current_user)):
    with services._session() as db:
        return {"layout": repo.get_layout(_profile(db, actor))}


@router.put("/layout")
def api_put_layout(body: LayoutBody, actor: str = Depends(get_current_user)):
    with services._session() as db:
        repo.set_layout(db, _profile(db, actor), [list(t) for t in body.layout])
        return {"layout": [list(t) for t in body.layout]}
