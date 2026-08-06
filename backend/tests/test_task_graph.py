"""AP-496: child tasks, task dependencies and roadmap milestones.

Covers the REST surface (subtask parenting, dependency add/remove, milestone
CRUD) plus the invariants that keep the graph sane: no self-links, no cycles,
no cross-project edges, and blocked-by derived from real statuses.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    admin_id, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    c.admin_id = admin_id
    yield c


def _project(client, name="P"):
    return client.post("/api/projects", json={"name": name}).json()["id"]


def _task(client, pid, title="T", **kw):
    body = {"project_id": pid, "title": title, **kw}
    res = client.post("/api/tasks", json=body)
    assert res.status_code == 200, res.text
    return res.json()


# ── child tasks ──────────────────────────────────────────────────────────

def test_task_can_be_parented_and_reports_children(client):
    pid = _project(client)
    parent = _task(client, pid, "Parent")
    child = _task(client, pid, "Child")

    res = client.patch(f"/api/tasks/{child['id']}", json={"parent_id": parent["id"]})
    assert res.status_code == 200, res.text
    assert res.json()["parent_id"] == parent["id"]

    got = client.get(f"/api/tasks/{parent['id']}").json()
    assert got["subtasks"] == {"total": 1, "done": 0}

    subs = client.get(f"/api/tasks/{parent['id']}/subtasks").json()
    assert [s["id"] for s in subs] == [child["id"]]


def test_subtask_done_count_tracks_status(client):
    pid = _project(client)
    parent = _task(client, pid, "Parent")
    child = _task(client, pid, "Child")
    client.patch(f"/api/tasks/{child['id']}", json={"parent_id": parent["id"]})

    client.post(f"/api/tasks/{child['id']}/move", json={"status": "done"})

    assert client.get(f"/api/tasks/{parent['id']}").json()["subtasks"] == {
        "total": 1, "done": 1}


def test_parent_detach_with_empty_string(client):
    pid = _project(client)
    parent = _task(client, pid, "Parent")
    child = _task(client, pid, "Child")
    client.patch(f"/api/tasks/{child['id']}", json={"parent_id": parent["id"]})

    res = client.patch(f"/api/tasks/{child['id']}", json={"parent_id": ""})
    assert res.status_code == 200
    assert res.json()["parent_id"] is None


def test_task_cannot_be_its_own_parent(client):
    pid = _project(client)
    t = _task(client, pid)
    res = client.patch(f"/api/tasks/{t['id']}", json={"parent_id": t["id"]})
    assert res.status_code == 400


def test_parent_cycle_rejected(client):
    pid = _project(client)
    a = _task(client, pid, "A")
    b = _task(client, pid, "B")
    client.patch(f"/api/tasks/{b['id']}", json={"parent_id": a["id"]})
    # a under b would close the loop a → b → a
    res = client.patch(f"/api/tasks/{a['id']}", json={"parent_id": b["id"]})
    assert res.status_code == 400
    assert "cycle" in res.json()["detail"].lower()


def test_parent_must_be_same_project(client):
    p1, p2 = _project(client, "One"), _project(client, "Two")
    a = _task(client, p1, "A")
    b = _task(client, p2, "B")
    res = client.patch(f"/api/tasks/{b['id']}", json={"parent_id": a["id"]})
    assert res.status_code == 400


def test_deleting_parent_orphans_children_not_deletes_them(client):
    pid = _project(client)
    parent = _task(client, pid, "Parent")
    child = _task(client, pid, "Child")
    client.patch(f"/api/tasks/{child['id']}", json={"parent_id": parent["id"]})

    client.delete(f"/api/tasks/{parent['id']}")

    got = client.get(f"/api/tasks/{child['id']}")
    assert got.status_code == 200
    assert got.json()["parent_id"] is None


# ── dependencies ─────────────────────────────────────────────────────────

def test_add_and_list_dependency(client):
    pid = _project(client)
    a = _task(client, pid, "A")
    b = _task(client, pid, "B")

    res = client.post(f"/api/projects/{pid}/dependencies",
                      json={"task_id": b["id"], "depends_on_id": a["id"]})
    assert res.status_code == 200, res.text
    dep = res.json()
    assert dep["task_id"] == b["id"] and dep["depends_on_id"] == a["id"]

    deps = client.get(f"/api/projects/{pid}/dependencies").json()
    assert [d["id"] for d in deps] == [dep["id"]]


def test_blocked_by_clears_when_blocker_is_done(client):
    pid = _project(client)
    a = _task(client, pid, "A")
    b = _task(client, pid, "B")
    client.post(f"/api/projects/{pid}/dependencies",
                json={"task_id": b["id"], "depends_on_id": a["id"]})

    got = client.get(f"/api/tasks/{b['id']}").json()
    assert [d["id"] for d in got["blocked_by"]] == [a["id"]]
    assert got["is_blocked"] is True
    assert [d["id"] for d in got["blocks"]] == []

    assert [d["id"] for d in client.get(f"/api/tasks/{a['id']}").json()["blocks"]] \
        == [b["id"]]

    client.post(f"/api/tasks/{a['id']}/move", json={"status": "done"})

    got = client.get(f"/api/tasks/{b['id']}").json()
    assert got["is_blocked"] is False
    assert [d["id"] for d in got["blocked_by"]] == [a["id"]]  # edge still there


def test_self_dependency_rejected(client):
    pid = _project(client)
    a = _task(client, pid, "A")
    res = client.post(f"/api/projects/{pid}/dependencies",
                      json={"task_id": a["id"], "depends_on_id": a["id"]})
    assert res.status_code == 400


def test_dependency_cycle_rejected(client):
    pid = _project(client)
    a, b, c = (_task(client, pid, n) for n in "ABC")
    client.post(f"/api/projects/{pid}/dependencies",
                json={"task_id": b["id"], "depends_on_id": a["id"]})
    client.post(f"/api/projects/{pid}/dependencies",
                json={"task_id": c["id"], "depends_on_id": b["id"]})

    res = client.post(f"/api/projects/{pid}/dependencies",
                      json={"task_id": a["id"], "depends_on_id": c["id"]})
    assert res.status_code == 400
    assert "cycle" in res.json()["detail"].lower()


def test_duplicate_dependency_is_idempotent(client):
    pid = _project(client)
    a = _task(client, pid, "A")
    b = _task(client, pid, "B")
    first = client.post(f"/api/projects/{pid}/dependencies",
                        json={"task_id": b["id"], "depends_on_id": a["id"]}).json()
    second = client.post(f"/api/projects/{pid}/dependencies",
                         json={"task_id": b["id"], "depends_on_id": a["id"]})
    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert len(client.get(f"/api/projects/{pid}/dependencies").json()) == 1


def test_cross_project_dependency_rejected(client):
    p1, p2 = _project(client, "One"), _project(client, "Two")
    a = _task(client, p1, "A")
    b = _task(client, p2, "B")
    res = client.post(f"/api/projects/{p1}/dependencies",
                      json={"task_id": a["id"], "depends_on_id": b["id"]})
    assert res.status_code == 400


def test_delete_dependency(client):
    pid = _project(client)
    a = _task(client, pid, "A")
    b = _task(client, pid, "B")
    dep = client.post(f"/api/projects/{pid}/dependencies",
                      json={"task_id": b["id"], "depends_on_id": a["id"]}).json()

    res = client.delete(f"/api/projects/{pid}/dependencies/{dep['id']}")
    assert res.status_code == 200
    assert client.get(f"/api/projects/{pid}/dependencies").json() == []


def test_deleting_task_removes_its_dependency_edges(client):
    pid = _project(client)
    a = _task(client, pid, "A")
    b = _task(client, pid, "B")
    client.post(f"/api/projects/{pid}/dependencies",
                json={"task_id": b["id"], "depends_on_id": a["id"]})

    client.delete(f"/api/tasks/{a['id']}")

    assert client.get(f"/api/projects/{pid}/dependencies").json() == []


# ── milestones ───────────────────────────────────────────────────────────

def test_milestone_crud_and_task_link(client):
    pid = _project(client)
    res = client.post(f"/api/projects/{pid}/milestones",
                      json={"title": "Beta", "due_date": "2026-09-01"})
    assert res.status_code == 200, res.text
    ms = res.json()
    assert ms["title"] == "Beta"
    assert ms["due_date"].startswith("2026-09-01")
    assert ms["total"] == 0 and ms["done"] == 0

    t = _task(client, pid, "Ship it")
    assert client.patch(f"/api/tasks/{t['id']}",
                        json={"milestone_id": ms["id"]}).status_code == 200

    listed = client.get(f"/api/projects/{pid}/milestones").json()
    assert listed[0]["total"] == 1 and listed[0]["done"] == 0
    assert listed[0]["progress"] == 0

    client.post(f"/api/tasks/{t['id']}/move", json={"status": "done"})
    listed = client.get(f"/api/projects/{pid}/milestones").json()
    assert listed[0]["done"] == 1 and listed[0]["progress"] == 100

    upd = client.patch(f"/api/projects/{pid}/milestones/{ms['id']}",
                       json={"title": "Beta 2", "status": "achieved"})
    assert upd.status_code == 200
    assert upd.json()["title"] == "Beta 2" and upd.json()["status"] == "achieved"

    assert client.delete(
        f"/api/projects/{pid}/milestones/{ms['id']}").status_code == 200
    assert client.get(f"/api/projects/{pid}/milestones").json() == []


def test_deleting_milestone_keeps_tasks(client):
    pid = _project(client)
    ms = client.post(f"/api/projects/{pid}/milestones",
                     json={"title": "Beta"}).json()
    t = _task(client, pid, "Ship it")
    client.patch(f"/api/tasks/{t['id']}", json={"milestone_id": ms["id"]})

    client.delete(f"/api/projects/{pid}/milestones/{ms['id']}")

    got = client.get(f"/api/tasks/{t['id']}")
    assert got.status_code == 200
    assert got.json()["milestone_id"] is None


def test_milestone_title_required(client):
    pid = _project(client)
    res = client.post(f"/api/projects/{pid}/milestones", json={"title": "  "})
    assert res.status_code == 400


# ── roadmap payload ──────────────────────────────────────────────────────

def test_roadmap_exposes_dependencies_and_milestones(client):
    pid = _project(client)
    a = _task(client, pid, "A", due_date="2026-09-10")
    b = _task(client, pid, "B", due_date="2026-09-20")
    client.post(f"/api/projects/{pid}/dependencies",
                json={"task_id": b["id"], "depends_on_id": a["id"]})
    client.post(f"/api/projects/{pid}/milestones",
                json={"title": "Beta", "due_date": "2026-09-30"})

    road = client.get(f"/api/projects/{pid}/roadmap").json()
    assert [(d["task_id"], d["depends_on_id"]) for d in road["dependencies"]] \
        == [(b["id"], a["id"])]
    assert [m["title"] for m in road["milestones"]] == ["Beta"]
    task_rows = [t for e in road["epics"] for t in e["tasks"]]
    blocked = next(t for t in task_rows if t["id"] == b["id"])
    assert blocked["is_blocked"] is True
    assert next(t for t in task_rows if t["id"] == a["id"])["is_blocked"] is False


# ── agent-facing surface (MCP calls these services directly) ─────────────

def test_create_task_can_land_nested_and_on_a_milestone(client):
    """Agents plan top-down: create the child already attached, in one call."""
    pid = _project(client)
    parent = _task(client, pid, "Parent")
    ms = client.post(f"/api/projects/{pid}/milestones", json={"title": "Beta"}).json()

    child = _task(client, pid, "Child", parent_id=parent["id"], milestone_id=ms["id"])
    assert child["parent_id"] == parent["id"]
    assert child["milestone_id"] == ms["id"]
    assert client.get(f"/api/tasks/{parent['id']}").json()["subtasks"]["total"] == 1


def test_create_task_rejects_a_cross_project_parent(client):
    p1, p2 = _project(client, "One"), _project(client, "Two")
    outsider = _task(client, p1, "A")
    res = client.post("/api/tasks", json={
        "project_id": p2, "title": "B", "parent_id": outsider["id"]})
    assert res.status_code == 400


def test_service_layer_exposes_the_graph_to_agents(pg, seed_admin):
    """The MCP tools call these `services` functions — they must exist and be
    actor-scoped, not just be reachable over REST."""
    from backend import services as core_services

    admin_id, _ = seed_admin
    project = core_services.create_project("Graph", actor="admin")
    pid = project["id"]
    a = core_services.create_task(pid, "A", actor="admin")
    b = core_services.create_task(pid, "B", actor="admin")

    dep = core_services.add_dependency(pid, b["id"], a["id"], actor="admin")
    assert [d["id"] for d in core_services.list_dependencies(pid, actor="admin")] \
        == [dep["id"]]

    ms = core_services.create_milestone(pid, "Beta", due_date="2026-09-01",
                                        actor="admin")
    core_services.update_task(b["id"], milestone_id=ms["id"], actor="admin")
    assert core_services.list_milestones(pid, actor="admin")[0]["total"] == 1

    core_services.update_task(b["id"], parent_id=a["id"], actor="admin")
    assert [t["id"] for t in core_services.list_subtasks(a["id"], actor="admin")] \
        == [b["id"]]

    # The roadmap an agent reads carries the graph, not just the task list.
    road = core_services.get_roadmap(pid)
    assert road["dependencies"][0]["depends_on_id"] == a["id"]
    assert road["milestones"][0]["title"] == "Beta"
    blocked = next(t for e in road["epics"] for t in e["tasks"] if t["id"] == b["id"])
    assert blocked["is_blocked"] is True

    assert core_services.remove_dependency(pid, dep["id"], actor="admin") is True
    assert core_services.list_dependencies(pid, actor="admin") == []
    assert core_services.delete_milestone(pid, ms["id"], actor="admin") is True


# ── access control ───────────────────────────────────────────────────────

def test_outsider_cannot_touch_the_graph(client, pg):
    """A profile with no membership on the project gets no read or write."""
    from backend import db as bdb
    from backend.db import privileged
    from backend.jwt_auth import create_token
    from backend.models import Profile, Role

    pid = _project(client)
    a = _task(client, pid, "A")
    b = _task(client, pid, "B")

    with privileged(), bdb.SessionLocal() as db:
        member_role = db.query(Role).filter(Role.name == "member").first()
        outsider_prof = Profile(name="outsider", account_type="human",
                                roles=[member_role], org_id=pg.org_id,
                                password_hash="")
        db.add(outsider_prof)
        db.commit()
        outsider_id = outsider_prof.id
    outsider = TestClient(app)
    outsider.headers["Authorization"] = (
        f"Bearer {create_token('outsider', outsider_id, ['member'], org_id=pg.org_id)}")

    assert outsider.post(f"/api/projects/{pid}/dependencies",
                         json={"task_id": b["id"], "depends_on_id": a["id"]}
                         ).status_code in (403, 404)
    assert outsider.get(f"/api/projects/{pid}/dependencies").status_code in (403, 404)
    assert outsider.post(f"/api/projects/{pid}/milestones",
                         json={"title": "X"}).status_code in (403, 404)
