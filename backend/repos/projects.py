"""Data access for the Project domain.

Starts the core repo layer with the queries the delete-cascade needs.
`project_repos` rows and the `Profile.default_project_id` pointer carry no ORM
cascade, so they must be cleared explicitly before `db.delete(project)`.
Other project reads still live in services.py (legacy) — migrate as touched.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import Date, case, cast, func, literal, or_, select

from backend.models import (Activity, Permission, ProfilePermission, ProjectRepo, Profile, Project, ProjectMember,
                            RolePermission, Status, Task, profile_roles)


def delete_project_repos(db, project_id: str) -> None:
    db.query(ProjectRepo).filter(ProjectRepo.project_id == project_id).delete(
        synchronize_session=False)


def clear_default_project_pointers(db, project_id: str) -> None:
    db.query(Profile).filter(Profile.default_project_id == project_id).update(
        {Profile.default_project_id: None}, synchronize_session=False)


def task_counts_by_project(db, project_ids: list[str]) -> dict[str, int]:
    """One aggregate COUNT for all given projects, instead of a per-project
    `len(p.tasks)` lazy-load (perf fix — list_projects was N+1)."""
    if not project_ids:
        return {}
    rows = (
        db.query(Task.project_id, func.count(Task.id))
        .filter(Task.project_id.in_(project_ids))
        .group_by(Task.project_id)
        .all()
    )
    return {project_id: count for project_id, count in rows}


# ── Home page ────────────────────────────────────────────────────────────
# Week math is Monday-start, UTC.

TREND_WEEKS = 6
FEED_LIMIT = 20
AVATAR_LIMIT = 5
_PALETTE = ["#7c4dff", "#2ecc71", "#ff7043", "#29b6f6", "#ec407a", "#ffca28", "#26a69a", "#8d6e63"]


def week_start(now: datetime) -> datetime:
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def project_colour(project_id: str) -> str:
    """Projects have no stored colour; derive a stable one from the id."""
    return _PALETTE[sum(map(ord, project_id)) % len(_PALETTE)]


def home_projects(db, profile: Profile) -> list[Project]:
    """Projects shown on Home, in ONE query: every project in the org for a read-all principal
    (``project.view_all`` via a role or an extra permission, or ``*`` / system), otherwise only memberships.

    Admins must see work agents do in projects the admin was never added to; a membership-only Home would
    hide that activity from the people overseeing it. The permission check lives inside the same statement
    so Home's query budget does not grow."""
    codes = ("project.view_all", "*")
    via_role = (select(literal(1)).select_from(profile_roles)
                .join(RolePermission, RolePermission.role_id == profile_roles.c.role_id)
                .join(Permission, Permission.id == RolePermission.permission_id)
                .where(profile_roles.c.profile_id == profile.id, Permission.codename.in_(codes)).exists())
    via_extra = (select(literal(1)).select_from(ProfilePermission)
                 .join(Permission, Permission.id == ProfilePermission.permission_id)
                 .where(ProfilePermission.profile_id == profile.id, Permission.codename.in_(codes)).exists())
    member = Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.profile_id == profile.id))
    read_all = or_(literal(bool(getattr(profile, "is_system", False))), via_role, via_extra)
    return db.query(Project).filter(or_(read_all, member)).order_by(Project.created_at.desc()).all()


def task_stats_by_project(db, project_ids: list[str], now: datetime) -> dict[str, dict]:
    """total/done/open/due_week/late/done_week/last_updated per project, one query."""
    ws = week_start(now)
    we = ws + timedelta(days=7)
    is_done = Status.name == "done"
    open_ = ~is_done
    rows = (
        db.query(
            Task.project_id,
            func.count(Task.id),
            func.count(case((is_done, 1))),
            func.count(case((open_, 1))),
            func.count(case((open_ & (Task.due_date >= ws) & (Task.due_date < we), 1))),
            func.count(case((open_ & (Task.due_date < now), 1))),
            func.count(case((is_done & (Task.completed_at >= ws), 1))),
            func.max(Task.updated_at),
        )
        .join(Status, Status.id == Task.status_id)
        .filter(Task.project_id.in_(project_ids))
        .group_by(Task.project_id).all()
    )
    keys = ("total", "done", "open", "due_week", "late", "done_week", "last_updated")
    return {r[0]: dict(zip(keys, r[1:])) for r in rows}


def done_trend_by_project(db, project_ids: list[str], now: datetime) -> dict[str, list[int]]:
    """Done-per-week for the last TREND_WEEKS weeks (oldest first), one query."""
    ws = week_start(now)
    first = ws - timedelta(weeks=TREND_WEEKS - 1)
    wk = func.date_trunc("week", Task.completed_at)
    rows = (
        db.query(Task.project_id, wk, func.count(Task.id))
        .join(Status, Status.id == Task.status_id)
        .filter(Task.project_id.in_(project_ids), Status.name == "done", Task.completed_at >= first)
        .group_by(Task.project_id, wk).all()
    )
    out = {pid: [0] * TREND_WEEKS for pid in project_ids}
    for pid, w, n in rows:
        idx = (w.astimezone(timezone.utc).replace(tzinfo=None) - first.replace(tzinfo=None)).days // 7
        if 0 <= idx < TREND_WEEKS:
            out[pid][idx] = n
    return out


def members_by_project(db, project_ids: list[str]) -> dict[str, list[Profile]]:
    rows = (db.query(ProjectMember.project_id, Profile)
            .join(Profile, Profile.id == ProjectMember.profile_id)
            .filter(ProjectMember.project_id.in_(project_ids))
            .order_by(Profile.name).all())
    out: dict[str, list[Profile]] = {}
    for pid, prof in rows:
        out.setdefault(pid, []).append(prof)
    return out


def recent_task_events(db, project_ids: list[str]) -> list[dict]:
    rows = (
        db.query(Activity, Task.key, Task.title, Project.id, Project.name)
        .join(Task, Task.id == Activity.task_id)
        .join(Project, Project.id == Task.project_id)
        .filter(Task.project_id.in_(project_ids), Activity.action.like("task.%"))
        .order_by(Activity.created_at.desc()).limit(FEED_LIMIT).all()
    )
    return [{"id": a.id, "actor": a.actor, "action": a.action, "detail": a.detail,
             "task_key": key, "task_title": title, "project_id": pid,
             "project_name": pname, "at": a.created_at.isoformat()}
            for a, key, title, pid, pname in rows]


def people_stats(db, project_ids: list[str], member_names: list[str], now: datetime) -> dict[str, dict]:
    """Per assignee: open tasks and distinct days with finished work this week."""
    ws = week_start(now)
    is_done = Status.name == "done"
    rows = (
        db.query(
            Task.assignee,
            func.count(case((~is_done, 1))),
            func.count(func.distinct(case((is_done & (Task.completed_at >= ws),
                                           cast(Task.completed_at, Date))))),
        )
        .join(Status, Status.id == Task.status_id)
        .filter(Task.project_id.in_(project_ids), Task.assignee.in_(member_names))
        .group_by(Task.assignee).all()
    )
    return {name: {"open": o, "days_done_this_week": d} for name, o, d in rows}


def get_layout(profile: Profile) -> list:
    try:
        return json.loads(profile.home_layout) if profile.home_layout else []
    except ValueError:
        return []


def set_layout(db, profile: Profile, layout: list) -> None:
    profile.home_layout = json.dumps(layout)
    db.commit()
