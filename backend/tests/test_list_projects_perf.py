"""list_projects must issue O(1) DB queries regardless of project/task/member
count (perf fix — was N+1: one lazy `len(p.tasks)` load per project plus one
lazy `m.profile` load per member)."""
from __future__ import annotations

from sqlalchemy import event

from backend.db import privileged
from backend import services as core_services
from backend.models import Profile, Role


def _make_member(pg, name: str) -> str:
    with privileged(), pg.SessionLocal() as db:
        member_role = db.query(Role).filter(Role.name == "member").first()
        profile = Profile(name=name, account_type="human", roles=[member_role],
                          org_id=pg.org_id, password_hash="")
        db.add(profile)
        db.commit()
        return profile.name


def _count_queries(engine, fn):
    count = 0

    def _before_cursor_execute(*args, **kwargs):
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)
    return count


def test_list_projects_query_count_is_constant(pg, seed_admin):
    member_names = [_make_member(pg, f"member{i}") for i in range(3)]

    def _make_project(n_tasks: int, n_members: int) -> None:
        core_services.create_project(
            f"Proj-{n_tasks}-{n_members}", actor="admin",
            initial_tasks=[{"title": f"t{i}"} for i in range(n_tasks)],
            members=member_names[:n_members],
        )

    _make_project(2, 1)
    small_count = _count_queries(pg.engine, lambda: core_services.list_projects(actor="admin"))

    for _ in range(5):
        _make_project(20, 3)
    large_count = _count_queries(pg.engine, lambda: core_services.list_projects(actor="admin"))

    assert small_count == large_count, (
        f"list_projects query count grew with data size: {small_count} -> {large_count}"
    )
    assert large_count < 10, f"list_projects issued {large_count} queries, expected O(1)"
