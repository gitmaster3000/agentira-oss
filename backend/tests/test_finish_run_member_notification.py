"""A finished run must surface to the humans on the project, not just as a
silent activity row. finish_run notifies project members (with a live broker
push) so the bell updates — this is the "no notification on run finished" fix.
"""

from __future__ import annotations

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime, RuntimeStatus, Run
from backend.models import Notification, Profile, Role


@pytest.fixture(autouse=True)
def test_db(pg):
    yield bdb.SessionLocal


def _seed_member(test_db) -> str:
    db = test_db()
    member_role = db.query(Role).filter(Role.name == "member").first()
    p = Profile(name="alice", account_type="human", roles=[member_role], password_hash="")
    db.add(p)
    db.commit()
    member_id = p.id
    db.close()
    return member_id


def _make_run(test_db) -> dict:
    _seed_member(test_db)
    db = test_db()
    rt = ForgeRuntime(daemon_id="d", provider="claude",
                      binary_path="/tmp/c", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    project = core_services.create_project("P", actor="alice")
    task = core_services.create_task(project["id"], "Build the thing", actor="alice")
    agent = forge_services.create_agent(name="A", executor_type="cli", runtime_id=rt_id)
    run = forge_services.create_run(
        agent_id=agent["id"], task_id=task["id"], project_id=project["id"],
    )
    # finish_run(succeeded) requires a deliverable — give the run a diff.
    with bdb.SessionLocal() as sess:
        sess.query(Run).filter(Run.id == run["id"]).update({Run.diff_stat: "1 file"})
        sess.commit()
    return {"run_id": run["id"], "task_id": task["id"]}


def _member_notes(test_db, type_: str) -> list[Notification]:
    db = test_db()
    try:
        alice = db.query(Profile).filter(Profile.name == "alice").first()
        return (db.query(Notification)
                  .filter(Notification.profile_id == alice.id,
                          Notification.type == type_)
                  .all())
    finally:
        db.close()


def test_succeeded_notifies_project_member(test_db):
    s = _make_run(test_db)
    forge_services.finish_run(s["run_id"], outcome="succeeded", summary="all green")
    notes = _member_notes(test_db, "forge.run.succeeded")
    assert len(notes) == 1
    assert s["task_id"] in notes[0].link
    assert "all green" in notes[0].title


def test_failed_notifies_project_member(test_db):
    s = _make_run(test_db)
    forge_services.finish_run(s["run_id"], outcome="failed", summary="crashed")
    notes = _member_notes(test_db, "forge.run.failed")
    assert len(notes) == 1


def test_chat_run_also_notifies(test_db):
    """A run is a run — a chat-triggered run the agent declares finished still
    notifies the project member (the human may have left the chat thread). The
    activity-feed comment stays chat-excluded, but the bell fires."""
    s = _make_run(test_db)
    with bdb.SessionLocal() as sess:
        sess.query(Run).filter(Run.id == s["run_id"]).update(
            {Run.trigger_event: "chat"})
        sess.commit()
    forge_services.finish_run(s["run_id"], outcome="succeeded", summary="done")
    assert len(_member_notes(test_db, "forge.run.succeeded")) == 1
