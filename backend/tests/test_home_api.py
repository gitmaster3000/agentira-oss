"""GET /api/home returns every Home section in one response with a constant
query count; GET/PUT /api/home/layout are per user."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from backend.db import privileged
from backend.models import Profile, Role, Status, Task, allow_task_write
from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    _, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def _project(client, name, n_tasks):
    pid = client.post("/api/projects", json={"name": name, "initial_tasks": []}).json()["id"]
    for i in range(n_tasks):
        client.post("/api/tasks", json={"project_id": pid, "title": f"t{i}"})
    return pid


def _age_tasks(pg, project_id, done_n, due_delta_days):
    """Mark first done_n tasks done; give the rest a due date."""
    with privileged(), pg.SessionLocal() as db:
        done = db.query(Status).filter(Status.name == "done").one()
        tasks = db.query(Task).filter(Task.project_id == project_id).order_by(Task.created_at).all()
        due = datetime.now(timezone.utc) + timedelta(days=due_delta_days)
        with allow_task_write():
            for i, t in enumerate(tasks):
                if i < done_n:
                    t.status_id = done.id
                else:
                    t.due_date = due
        db.commit()


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
    assert big <= 14


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
