"""GET /api/home returns every Home section in one response with a constant
query count; GET/PUT /api/home/layout are per user."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from backend.db import privileged
from backend.models import Profile, Role, Task
from backend.rest_api import app


_CLIENT = [None]


@pytest.fixture
def client(seed_admin):
    _, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    _CLIENT[0] = c
    return c


def _project(client, name, n_tasks):
    pid = client.post("/api/projects", json={"name": name, "initial_tasks": []}).json()["id"]
    for i in range(n_tasks):
        client.post("/api/tasks", json={"project_id": pid, "title": f"t{i}"})
    return pid


def _move(task_id, status):
    return _CLIENT[0].post(f"/api/tasks/{task_id}/move", json={"status": status})


def _age_tasks(pg, project_id, done_n, due_delta_days):
    """Mark first done_n tasks done (via the service, so completed_at is set); give the rest a due date."""
    with privileged(), pg.SessionLocal() as db:
        ids = [t.id for t in db.query(Task).filter(Task.project_id == project_id).order_by(Task.created_at)]
        due = datetime.now(timezone.utc) + timedelta(days=due_delta_days)
        for t in db.query(Task).filter(Task.id.in_(ids[done_n:])):
            t.due_date = due
        db.commit()
    for tid in ids[:done_n]:
        assert _move(tid, "done").status_code == 200


def _count(engine, fn):
    n = 0

    def hook(*a, **k):
        nonlocal n
        n += 1
    event.listen(engine, "before_cursor_execute", hook)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", hook)
    return n


def test_home_shape_and_numbers(pg, client):
    pid = _project(client, "Alpha", 4)
    _age_tasks(pg, pid, done_n=1, due_delta_days=-3)
    body = client.get("/api/home").json()
    assert set(body) == {"week", "projects", "activity", "people", "week_summary"}
    assert body["week_summary"] is None
    p = body["projects"][0]
    assert p["name"] == "Alpha" and p["pct_done"] == 25 and p["open"] == 3
    assert p["late"] == 3 and p["member_count"] >= 1
    assert len(p["done_per_week"]) == 6 and sum(p["done_per_week"]) == 1
    assert body["week"]["planned"] == 4 and body["week"]["late"] == 3
    assert body["week"]["done"] == 1
    assert body["activity"] and body["activity"][0]["task_key"]


def test_home_query_count_is_constant(pg, client):
    _project(client, "Small", 2)
    small = _count(pg.engine, lambda: client.get("/api/home"))
    for i in range(4):
        _project(client, f"Big{i}", 15)
    big = _count(pg.engine, lambda: client.get("/api/home"))
    assert small == big, f"query count grew {small} -> {big}"
    assert big <= 8, f"/api/home used {big} queries"


def test_home_only_member_projects(pg, client):
    _project(client, "Mine", 1)
    with privileged(), pg.SessionLocal() as db:
        role = db.query(Role).filter(Role.name == "member").first()
        db.add(Profile(name="bob", account_type="human", roles=[role],
                       org_id=pg.org_id, password_hash=""))
        db.commit()
    from backend.jwt_auth import create_token
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer " + create_token("bob", "x", ["member"], org_id=pg.org_id)
    body = c.get("/api/home").json()
    assert body["projects"] == [] and body["week"]["planned"] == 0


def test_layout_roundtrip_per_user(pg, client):
    assert client.get("/api/home/layout").json() == {"layout": []}
    r = client.put("/api/home/layout", json={"layout": [["week", "wide"], ["people", "small"]]})
    assert r.status_code == 200
    assert client.get("/api/home/layout").json()["layout"] == [["week", "wide"], ["people", "small"]]
    assert client.put("/api/home/layout", json={"layout": [["x"]]}).status_code == 422


def _one_done_task(pg, client):
    pid = _project(client, "Beta", 1)
    _age_tasks(pg, pid, done_n=1, due_delta_days=0)
    with privileged(), pg.SessionLocal() as db:
        return db.query(Task).filter(Task.project_id == pid).one().id


def test_edit_after_done_does_not_change_done_week(pg, client):
    tid = _one_done_task(pg, client)
    assert client.get("/api/home").json()["week"]["done"] == 1
    # the task was actually finished a month ago
    with privileged(), pg.SessionLocal() as db:
        t = db.get(Task, tid)
        t.completed_at = datetime.now(timezone.utc) - timedelta(days=30)
        db.commit()
    before = client.get("/api/home").json()
    assert before["week"]["done"] == 0
    r = client.patch(f"/api/tasks/{tid}", json={"title": "renamed", "tags": ["x"]})
    assert r.status_code == 200
    after = client.get("/api/home").json()
    assert after["week"]["done"] == 0
    assert after["projects"][0]["done_per_week"] == before["projects"][0]["done_per_week"]
    assert after["people"] == before["people"]


def test_reopen_clears_completed_at(pg, client):
    tid = _one_done_task(pg, client)
    with privileged(), pg.SessionLocal() as db:
        assert db.get(Task, tid).completed_at is not None
    assert _move(tid, "todo").status_code == 200
    with privileged(), pg.SessionLocal() as db:
        assert db.get(Task, tid).completed_at is None
    assert client.get("/api/home").json()["week"]["done"] == 0


def test_migration_backfills_completed_at_from_move_activity(pg, client):
    from sqlalchemy import text
    from backend.db import run_migrations
    tid = _one_done_task(pg, client)
    with pg.engine.begin() as conn:
        moved_at = conn.execute(text(
            "SELECT max(created_at) FROM activities WHERE task_id=:t AND action='task.move'"),
            {"t": tid}).scalar()
        conn.execute(text("ALTER TABLE tasks DROP COLUMN completed_at"))
    run_migrations()
    with pg.engine.begin() as conn:
        got = conn.execute(text("SELECT completed_at FROM tasks WHERE id=:t"), {"t": tid}).scalar()
    assert got == moved_at


def _profile_token(pg, name, role_name):
    from backend.jwt_auth import create_token
    with privileged(), pg.SessionLocal() as db:
        role = db.query(Role).filter(Role.name == role_name).first()
        prof = Profile(name=name, account_type="human", roles=[role], org_id=pg.org_id, password_hash="")
        db.add(prof)
        db.commit()
        return create_token(name, prof.id, [role_name], org_id=pg.org_id)


def _as(token):
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_home_shows_every_project_to_a_read_all_principal(pg, client):
    """An admin must see work done by agents in projects the admin was never added to:
    a Home that only lists membership would hide agent activity from the people overseeing it."""
    other = _as(_profile_token(pg, "other-admin", "admin"))
    hidden = other.post("/api/projects", json={"name": "AgentOnly", "initial_tasks": []}).json()["id"]
    other.post("/api/tasks", json={"project_id": hidden, "title": "agent task"})
    mine = _project(client, "Mine", 1)

    body = client.get("/api/home").json()
    ids = {p["id"] for p in body["projects"]}
    assert {hidden, mine} <= ids
    assert any(a["project_id"] == hidden for a in body["activity"]) if body["activity"] and "project_id" in body["activity"][0] else True
    assert body["week"]["planned"] >= 2  # stats cover the project the admin is not a member of


def test_home_still_scopes_non_privileged_users_to_membership(pg, client):
    other = _as(_profile_token(pg, "other-admin", "admin"))
    hidden = other.post("/api/projects", json={"name": "NotYours", "initial_tasks": []}).json()["id"]
    member = _as(_profile_token(pg, "plain-member", "member"))
    assert hidden not in {p["id"] for p in member.get("/api/home").json()["projects"]}
