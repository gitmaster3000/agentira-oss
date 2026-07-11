"""AP-433: list_profiles / list_project_members / list_epics were classic
N+1s — each row lazy-loaded its own relationships (Profile.roles,
Profile.extra_permissions(+.permission), Profile.project_memberships,
Epic.tasks), so query count scaled with row count. Prod logs showed these
three as the slowest endpoints (5.1s / 4.8s / 3.8s avg).

Proof: query count for N rows must stay flat (a small constant), not grow
with N. Counts N+1-many small SELECTs before the fix; this is the
regression test for the selectinload / batch-count fix in services.py.
"""
import pytest
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

import backend.models  # noqa: F401
import backend.forge.models  # noqa: F401
from backend.db import Base
from backend import services

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    with patch("backend.services.SessionLocal", TestSession):
        with patch("backend.db.engine", engine):
            services.bootstrap()
            yield
    Base.metadata.drop_all(bind=engine)


@contextmanager
def count_queries():
    counter = {"n": 0}

    def _tick(*args, **kwargs):
        counter["n"] += 1

    event.listen(engine, "after_cursor_execute", _tick)
    try:
        yield counter
    finally:
        event.remove(engine, "after_cursor_execute", _tick)


_next_user = [0]


def _make_profiles(n):
    """Returns [(id, name), ...] for n freshly created profiles."""
    if not any(p["codename"] == "perf.read" for p in services.list_permissions()):
        services.create_permission("perf.read")
    out = []
    for _ in range(n):
        i = _next_user[0]
        _next_user[0] += 1
        name = f"user{i}"
        p = services.create_profile(name, roles=["member"])
        services.grant_profile_permission(p["id"], "perf.read")
        out.append((p["id"], name))
    return out


# ── list_profiles ──────────────────────────────────────────────────────

def test_list_profiles_query_count_does_not_scale_with_row_count():
    _make_profiles(2)
    with count_queries() as c:
        services.list_profiles()
    small_n = c["n"]

    _make_profiles(8)  # +8 more rows, 10 total
    with count_queries() as c:
        services.list_profiles()
    big_n = c["n"]

    assert big_n == small_n, f"query count grew with row count ({small_n} -> {big_n}): N+1 regressed"


def test_list_profiles_still_returns_roles_and_permissions():
    made = _make_profiles(3)
    made_ids = {i for i, _ in made}
    profiles = [p for p in services.list_profiles() if p["id"] in made_ids]
    assert len(profiles) == 3
    for p in profiles:
        assert "member" in p["roles"]
        assert "perf.read" in p["extra_permissions"]


# ── list_project_members ─────────────────────────────────────────────

def test_list_project_members_query_count_does_not_scale_with_row_count():
    project = services.create_project("Perf Project")
    for _pid, name in _make_profiles(2):
        services.add_project_member(project["id"], name)
    with count_queries() as c:
        services.list_project_members(project["id"])
    small_n = c["n"]

    for _pid, name in _make_profiles(8):
        services.add_project_member(project["id"], name)
    with count_queries() as c:
        services.list_project_members(project["id"])
    big_n = c["n"]

    assert big_n == small_n, f"query count grew with row count ({small_n} -> {big_n}): N+1 regressed"


# ── list_epics ────────────────────────────────────────────────────────

def test_list_epics_query_count_does_not_scale_with_row_count():
    project = services.create_project("Epic Perf Project")
    for i in range(2):
        e = services.create_epic(project["id"], f"Epic {i}")
        services.create_task(project["id"], f"Task {i}", epic_id=e["id"])
    with count_queries() as c:
        services.list_epics(project["id"])
    small_n = c["n"]

    for i in range(2, 10):
        e = services.create_epic(project["id"], f"Epic {i}")
        services.create_task(project["id"], f"Task {i}", epic_id=e["id"])
    with count_queries() as c:
        services.list_epics(project["id"])
    big_n = c["n"]

    assert big_n == small_n, f"query count grew with row count ({small_n} -> {big_n}): N+1 regressed"


def test_list_epics_still_returns_correct_task_counts():
    project = services.create_project("Epic Count Project")
    e1 = services.create_epic(project["id"], "Epic 1")
    e2 = services.create_epic(project["id"], "Epic 2")
    services.create_task(project["id"], "T1", epic_id=e1["id"])
    services.create_task(project["id"], "T2", epic_id=e1["id"])
    services.create_task(project["id"], "T3", epic_id=e2["id"])

    epics = {e["id"]: e for e in services.list_epics(project["id"])}
    assert epics[e1["id"]]["task_count"] == 2
    assert epics[e2["id"]]["task_count"] == 1
