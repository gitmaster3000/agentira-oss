"""Run notifications carry structured meta (agent, task, project, status) so
the Inbox can render a rich row; list_notifications exposes it."""

from __future__ import annotations

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import runs as forge_runs
from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime, RuntimeStatus
from backend.models import Notification, Profile, ProjectMember


@pytest.fixture(autouse=True)
def test_db(pg):
    yield bdb.SessionLocal


def _setup(test_db) -> dict:
    db = test_db()
    rt = ForgeRuntime(daemon_id="d", provider="claude",
                      binary_path="/tmp/c", status=RuntimeStatus.ONLINE)
    member = Profile(name="human-1", account_type="human", password_hash="")
    db.add_all([rt, member])
    db.commit()
    rt_id, member_id = rt.id, member.id
    db.close()
    project = core_services.create_project("Acme", actor="system")
    db = test_db()
    db.add(ProjectMember(project_id=project["id"], profile_id=member_id))
    db.commit()
    db.close()
    task = core_services.create_task(project["id"], "Build the thing", actor="system")
    agent = forge_services.create_agent(name="coder-1", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(agent_id=agent["id"], task_id=task["id"],
                                    project_id=project["id"])
    return {"run_id": run["id"], "member_id": member_id, "task": task}


def _latest(member_id: str, type_: str) -> dict:
    rows = core_services.list_notifications(member_id, unread_only=False)
    return next(n for n in rows if n["type"] == type_)


def test_started_notification_has_agent_task_project_meta(test_db):
    s = _setup(test_db)
    forge_runs.start(s["run_id"])
    meta = _latest(s["member_id"], "forge.run.started")["meta"]
    assert meta["status"] == "running"
    assert meta["agent_name"] == "coder-1"
    assert meta["task_title"] == "Build the thing"
    assert meta["task_key"] == s["task"]["key"]
    assert meta["project_name"] == "Acme"


def test_completed_notification_has_duration_and_cost(test_db):
    s = _setup(test_db)
    forge_runs.start(s["run_id"])
    forge_runs.complete(s["run_id"], cost_usd=0.5)
    meta = _latest(s["member_id"], "forge.run.completed")["meta"]
    assert meta["status"] == "completed"
    assert meta["cost_usd"] == 0.5
    assert "duration_ms" in meta


def test_failed_notification_has_error(test_db):
    s = _setup(test_db)
    forge_runs.start(s["run_id"])
    forge_runs.complete(s["run_id"], error="daemon lost heartbeat")
    meta = _latest(s["member_id"], "forge.run.failed")["meta"]
    assert meta["status"] == "failed"
    assert meta["error"] == "daemon lost heartbeat"


def test_legacy_notification_meta_is_none(test_db):
    db = test_db()
    p = Profile(name="legacy", account_type="human", password_hash="")
    db.add(p)
    db.commit()
    db.add(Notification(profile_id=p.id, type="task.assign", title="t", link=""))
    db.commit()
    pid = p.id
    db.close()
    assert core_services.list_notifications(pid)[0]["meta"] is None
