"""Batch task creation: a whole plan (tasks + dependency edges) in one atomic call."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    _, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    yield c


def _project(client, name="P"):
    pid = client.post("/api/projects", json={"name": name}).json()["id"]
    client.baseline = _counts(client, pid)
    return pid


def _batch(client, pid, tasks):
    return client.post(f"/api/projects/{pid}/tasks/batch", json={"tasks": tasks})


def _counts(client, pid):
    tasks = client.get("/api/tasks", params={"project_id": pid}).json()
    deps = client.get(f"/api/projects/{pid}/dependencies").json()
    return len(tasks), len(deps)


def test_batch_creates_tasks_and_edges(client):
    pid = _project(client)
    res = _batch(client, pid, [
        {"ref": "a", "title": "A"},
        {"ref": "b", "title": "B", "depends_on_refs": ["a"], "priority": "high"},
        {"ref": "c", "title": "C", "depends_on_refs": ["a", "b"]},
    ])
    assert res.status_code == 200, res.text
    out = res.json()
    assert [r["ref"] for r in out] == ["a", "b", "c"]
    assert all(r["id"] and r["key"] for r in out)
    assert len({r["key"] for r in out}) == 3

    ids = {r["ref"]: r["id"] for r in out}
    edges = {(d["task_id"], d["depends_on_id"])
             for d in client.get(f"/api/projects/{pid}/dependencies").json()}
    assert edges == {(ids["b"], ids["a"]), (ids["c"], ids["a"]), (ids["c"], ids["b"])}
    assert client.get(f"/api/tasks/{ids['b']}").json()["priority"] == "high"


def test_batch_forward_reference_ok(client):
    pid = _project(client)
    res = _batch(client, pid, [
        {"ref": "b", "title": "B", "depends_on_refs": ["a"]},
        {"ref": "a", "title": "A"},
    ])
    assert res.status_code == 200, res.text
    assert _counts(client, pid) == (client.baseline[0] + 2, client.baseline[1] + 1)


def test_batch_cycle_rejected_no_writes(client):
    pid = _project(client)
    res = _batch(client, pid, [
        {"ref": "a", "title": "A", "depends_on_refs": ["c"]},
        {"ref": "b", "title": "B", "depends_on_refs": ["a"]},
        {"ref": "c", "title": "C", "depends_on_refs": ["b"]},
    ])
    assert res.status_code == 400
    assert "cycle" in res.text
    assert _counts(client, pid) == client.baseline


def test_batch_unknown_ref_rejected_no_writes(client):
    pid = _project(client)
    res = _batch(client, pid, [
        {"ref": "a", "title": "A"},
        {"ref": "b", "title": "B", "depends_on_refs": ["nope"]},
    ])
    assert res.status_code == 400
    assert "nope" in res.text
    assert _counts(client, pid) == client.baseline


def test_batch_self_dependency_rejected(client):
    pid = _project(client)
    res = _batch(client, pid, [{"ref": "a", "title": "A", "depends_on_refs": ["a"]}])
    assert res.status_code == 400
    assert _counts(client, pid) == client.baseline


def test_batch_duplicate_or_missing_ref_rejected(client):
    pid = _project(client)
    dup = _batch(client, pid, [{"ref": "a", "title": "A"}, {"ref": "a", "title": "A2"}])
    assert dup.status_code == 400
    missing = _batch(client, pid, [{"title": "A"}])
    assert missing.status_code in (400, 422)
    assert _counts(client, pid) == client.baseline


def test_batch_late_invalid_entry_rolls_back_earlier_tasks(client):
    pid = _project(client)
    res = _batch(client, pid, [
        {"ref": "a", "title": "A"},
        {"ref": "b", "title": "B", "priority": "bogus"},
    ])
    assert res.status_code == 400
    assert _counts(client, pid) == client.baseline


def test_batch_rolled_back_keys_not_burned(client):
    pid = _project(client)
    first = _batch(client, pid, [{"ref": "a", "title": "A"}]).json()[0]["key"]
    _batch(client, pid, [{"ref": "a", "title": "A"}, {"ref": "b", "title": "B", "priority": "bogus"}])
    second = _batch(client, pid, [{"ref": "a", "title": "A"}]).json()[0]["key"]
    prefix, num = first.rsplit("-", 1)
    assert second == f"{prefix}-{int(num) + 1}"


def test_batch_empty_and_oversized_rejected(client):
    pid = _project(client)
    assert _batch(client, pid, []).status_code == 400
    big = [{"ref": f"r{i}", "title": "T"} for i in range(201)]
    assert _batch(client, pid, big).status_code == 400


def test_batch_unknown_project_404(client):
    res = _batch(client, "does-not-exist", [{"ref": "a", "title": "A"}])
    assert res.status_code in (400, 403, 404)
