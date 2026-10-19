"""AP-705: a task that ever changed status (transition_events /
gate_evaluations rows) must still be deletable, via service and REST; the
delete endpoints share one 404/403/409 contract."""
import pytest
from fastapi.testclient import TestClient

from backend import services
from backend.db import SessionLocal
from backend.forge.models import GateEvaluation, TransitionEvent
from backend.forge.repos import transitions
from backend.models import Task
from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    _admin_id, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def _task_with_history(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    tid = client.post("/api/tasks", json={"project_id": pid, "title": "t"}).json()["id"]
    assert client.post(f"/api/tasks/{tid}/move", json={"status": "todo"}).status_code == 200
    with SessionLocal() as db:
        transitions.record_gate_evaluation(
            db, task_id=tid, from_status="todo", to_status="in_progress",
            gate_id="g", evidence_snapshot={}, outcome="allow", reason="",
            duration_ms=1)
        db.commit()
        assert db.query(TransitionEvent).filter_by(task_id=tid).count() >= 1
    return pid, tid


def test_delete_task_with_status_history(client):
    pid, tid = _task_with_history(client)

    r = client.delete(f"/api/tasks/{tid}")

    assert r.status_code == 200 and r.json() == {"ok": True}
    with SessionLocal() as db:
        assert db.get(Task, tid) is None
        assert db.query(TransitionEvent).filter_by(task_id=tid).count() == 0
        assert db.query(GateEvaluation).filter_by(task_id=tid).count() == 0


def test_delete_project_with_status_history(client):
    pid, tid = _task_with_history(client)

    assert client.delete(f"/api/projects/{pid}").status_code == 200
    with SessionLocal() as db:
        assert db.query(TransitionEvent).filter_by(task_id=tid).count() == 0


def test_delete_task_does_not_touch_other_tasks_history(client):
    pid, tid = _task_with_history(client)
    other = client.post("/api/tasks", json={"project_id": pid, "title": "o"}).json()["id"]
    client.post(f"/api/tasks/{other}/move", json={"status": "todo"})

    client.delete(f"/api/tasks/{tid}")

    with SessionLocal() as db:
        assert db.query(TransitionEvent).filter_by(task_id=other).count() >= 1


@pytest.mark.parametrize("path", ["tasks", "epics", "projects"])
def test_delete_missing_is_404(client, path):
    assert client.delete(f"/api/{path}/nope").status_code == 404


def test_delete_epic_unlinks_tasks(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    eid = client.post(f"/api/projects/{pid}/epics", json={"title": "E"}).json()["id"]
    tid = client.post("/api/tasks", json={"project_id": pid, "title": "t",
                                          "epic_id": eid}).json()["id"]

    assert client.delete(f"/api/epics/{eid}").status_code == 200
    with SessionLocal() as db:
        assert db.get(Task, tid).epic_id is None


def test_fk_violation_maps_to_409_and_is_logged(client, monkeypatch, caplog):
    from sqlalchemy.exc import IntegrityError
    pid, tid = _task_with_history(client)

    def boom(task_id, actor="system"):
        raise IntegrityError("DELETE", {}, Exception("fk"))
    monkeypatch.setattr(services, "delete_task", boom)

    with caplog.at_level("ERROR", logger="agentira.delete"):
        r = client.delete(f"/api/tasks/{tid}")

    assert r.status_code == 409
    assert "can't be deleted" in r.json()["detail"]
    assert any(tid in rec.getMessage() for rec in caplog.records)
