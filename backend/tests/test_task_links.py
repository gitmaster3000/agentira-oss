"""AP-507: typed task links — every link writes both complementary edges."""

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


def _task(client, pid, title="T"):
    res = client.post("/api/tasks", json={"project_id": pid, "title": title})
    assert res.status_code == 200, res.text
    return res.json()


def _links(client, task_id):
    res = client.get(f"/api/tasks/{task_id}/links")
    assert res.status_code == 200, res.text
    return res.json()


def _add(client, task_id, other_id, link_type):
    return client.post(f"/api/tasks/{task_id}/links",
                       json={"other_task_id": other_id, "link_type": link_type})


@pytest.mark.parametrize("link_type,inverse", [
    ("depends_on", "blocks"),
    ("blocks", "depends_on"),
    ("relates_to", "relates_to"),
    ("duplicates", "duplicated_by"),
    ("duplicated_by", "duplicates"),
    ("child_of", "parent_of"),
    ("parent_of", "child_of"),
])
def test_link_sets_the_complementary_edge_on_the_other_task(client, link_type, inverse):
    pid = _project(client)
    a, b = _task(client, pid, "A"), _task(client, pid, "B")

    res = _add(client, a["id"], b["id"], link_type)
    assert res.status_code == 200, res.text

    mine = _links(client, a["id"])
    assert [(link["type"], link["task"]["id"]) for link in mine] == [(link_type, b["id"])]

    theirs = _links(client, b["id"])
    assert [(link["type"], link["task"]["id"]) for link in theirs] == [(inverse, a["id"])]


def test_depends_on_link_feeds_blocked_by(client):
    pid = _project(client)
    a, b = _task(client, pid, "A"), _task(client, pid, "B")
    _add(client, a["id"], b["id"], "depends_on")

    got = client.get(f"/api/tasks/{a['id']}").json()
    assert [t["id"] for t in got["blocked_by"]] == [b["id"]]
    assert got["is_blocked"] is True


def test_relates_to_does_not_block(client):
    pid = _project(client)
    a, b = _task(client, pid, "A"), _task(client, pid, "B")
    _add(client, a["id"], b["id"], "relates_to")

    got = client.get(f"/api/tasks/{a['id']}").json()
    assert got["blocked_by"] == []
    assert got["is_blocked"] is False
    assert client.get(f"/api/projects/{pid}/dependencies").json() == []


def test_child_of_link_sets_the_parent(client):
    pid = _project(client)
    child, parent = _task(client, pid, "C"), _task(client, pid, "P")
    _add(client, child["id"], parent["id"], "child_of")

    assert client.get(f"/api/tasks/{child['id']}").json()["parent_id"] == parent["id"]
    subs = client.get(f"/api/tasks/{parent['id']}/subtasks").json()
    assert [s["id"] for s in subs] == [child["id"]]


def test_removing_a_link_clears_both_ends(client):
    pid = _project(client)
    a, b = _task(client, pid, "A"), _task(client, pid, "B")
    _add(client, a["id"], b["id"], "depends_on")

    link_id = _links(client, a["id"])[0]["id"]
    res = client.delete(f"/api/tasks/{a['id']}/links/{link_id}")
    assert res.status_code == 200, res.text
    assert _links(client, a["id"]) == []
    assert _links(client, b["id"]) == []


def test_removing_a_hierarchy_link_from_either_end(client):
    pid = _project(client)
    child, parent = _task(client, pid, "C"), _task(client, pid, "P")
    _add(client, child["id"], parent["id"], "child_of")

    link_id = _links(client, parent["id"])[0]["id"]
    assert client.delete(f"/api/tasks/{parent['id']}/links/{link_id}").status_code == 200
    assert client.get(f"/api/tasks/{child['id']}").json()["parent_id"] is None


def test_self_link_rejected(client):
    pid = _project(client)
    a = _task(client, pid, "A")
    assert _add(client, a["id"], a["id"], "relates_to").status_code == 400


def test_unknown_link_type_rejected(client):
    pid = _project(client)
    a, b = _task(client, pid, "A"), _task(client, pid, "B")
    assert _add(client, a["id"], b["id"], "sort_of_like").status_code == 400


def test_dependency_cycle_rejected(client):
    pid = _project(client)
    a, b = _task(client, pid, "A"), _task(client, pid, "B")
    _add(client, a["id"], b["id"], "depends_on")
    assert _add(client, a["id"], b["id"], "blocks").status_code == 400


def test_parent_cycle_rejected(client):
    pid = _project(client)
    a, b = _task(client, pid, "A"), _task(client, pid, "B")
    _add(client, a["id"], b["id"], "child_of")
    assert _add(client, a["id"], b["id"], "parent_of").status_code == 400


def test_cross_project_link_rejected(client):
    a = _task(client, _project(client, "One"), "A")
    b = _task(client, _project(client, "Two"), "B")
    assert _add(client, a["id"], b["id"], "relates_to").status_code == 400


def test_relinking_the_same_pair_replaces_the_type(client):
    pid = _project(client)
    a, b = _task(client, pid, "A"), _task(client, pid, "B")
    _add(client, a["id"], b["id"], "relates_to")
    assert _add(client, a["id"], b["id"], "depends_on").status_code == 200

    assert [link["type"] for link in _links(client, a["id"])] == ["depends_on"]
    assert [link["type"] for link in _links(client, b["id"])] == ["blocks"]


def test_outsider_cannot_read_or_write_links(client, pg):
    from backend import db as bdb
    from backend.db import privileged
    from backend.jwt_auth import create_token
    from backend.models import Profile, Role

    pid = _project(client)
    a, b = _task(client, pid, "A"), _task(client, pid, "B")
    with privileged(), bdb.SessionLocal() as db:
        member_role = db.query(Role).filter(Role.name == "member").first()
        prof = Profile(name="outsider", account_type="human", roles=[member_role],
                       org_id=pg.org_id, password_hash="")
        db.add(prof)
        db.commit()
        outsider_id = prof.id
    outsider = TestClient(app)
    outsider.headers["Authorization"] = (
        f"Bearer {create_token('outsider', outsider_id, ['member'], org_id=pg.org_id)}")

    assert outsider.get(f"/api/tasks/{a['id']}/links").status_code in (403, 404)
    assert outsider.post(f"/api/tasks/{a['id']}/links",
                         json={"other_task_id": b["id"], "link_type": "relates_to"}
                         ).status_code in (403, 404)
