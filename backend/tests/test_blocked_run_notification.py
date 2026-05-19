"""AP-36: an agent that declares its run blocked / needs_input is asking
for human attention. finish_run must surface that as a Notification on
every admin profile, on top of the existing task-comment side effect.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime, RuntimeStatus
from backend.models import Notification, Profile, Role


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _seed_admin(test_db) -> None:
    """An admin profile must exist for _notify_admins to land its row;
    `_seed_defaults` only creates roles, not the bootstrap admin."""
    db = test_db()
    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if not db.query(Profile).filter(Profile.name == "admin").first():
        db.add(Profile(name="admin", role_id=admin_role.id, password_hash=""))
        db.commit()
    db.close()


def _make_run(test_db) -> dict:
    _seed_admin(test_db)
    db = test_db()
    rt = ForgeRuntime(daemon_id="d", provider="claude",
                      binary_path="/tmp/c", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "Build the thing",
                                     actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(
        agent_id=agent["id"], task_id=task["id"], project_id=project["id"],
    )
    return {"run_id": run["id"], "task_id": task["id"],
            "project_id": project["id"]}


def _admin_notifications(test_db, *, type_prefix: str = "") -> list[Notification]:
    db = test_db()
    try:
        q = (db.query(Notification)
               .join(Profile, Notification.profile_id == Profile.id)
               .join(Role, Profile.role_id == Role.id)
               .filter(Role.name == "admin"))
        if type_prefix:
            q = q.filter(Notification.type.startswith(type_prefix))
        return q.all()
    finally:
        db.close()


# ── blocked notifies ───────────────────────────────────────────────────

def test_finish_run_blocked_notifies_admins(test_db):
    s = _make_run(test_db)
    forge_services.finish_run(s["run_id"], outcome="blocked",
                              summary="auth library is missing client secret")
    notes = _admin_notifications(test_db, type_prefix="agent.")
    assert len(notes) >= 1
    n = notes[0]
    assert n.type == "agent.blocked"
    assert "blocked" in n.title.lower()
    assert "client secret" in n.title
    # Links into the task so the human lands on the right page.
    assert s["task_id"] in n.link or s["project_id"] in n.link


def test_finish_run_needs_input_notifies_admins(test_db):
    s = _make_run(test_db)
    forge_services.finish_run(s["run_id"], outcome="needs_input",
                              summary="which env should I deploy to?")
    notes = _admin_notifications(test_db, type_prefix="agent.")
    assert len(notes) >= 1
    assert notes[0].type == "agent.needs_input"
    assert "needs input" in notes[0].title.lower()


# ── succeeded / failed do NOT notify here ──────────────────────────────

def test_finish_run_succeeded_does_not_notify_admins(test_db):
    """Routine success isn't worth a notification — it would drown out
    the actionable blocked / needs_input ones."""
    s = _make_run(test_db)
    forge_services.finish_run(s["run_id"], outcome="succeeded",
                              summary="all green")
    assert _admin_notifications(test_db, type_prefix="agent.") == []


def test_finish_run_failed_does_not_notify_here(test_db):
    """Failed has its own run-complete notification path; finish_run
    shouldn't double-notify on the verdict."""
    s = _make_run(test_db)
    forge_services.finish_run(s["run_id"], outcome="failed",
                              summary="ran out of context")
    assert _admin_notifications(test_db, type_prefix="agent.") == []


# ── idempotent ─────────────────────────────────────────────────────────

def test_finish_run_blocked_summary_truncates_long_title(test_db):
    s = _make_run(test_db)
    forge_services.finish_run(s["run_id"], outcome="blocked",
                              summary="x" * 1000)
    notes = _admin_notifications(test_db, type_prefix="agent.")
    assert len(notes) == 1
    # Notification.title is varchar(255); we trim the summary before
    # building the title so we never violate the column.
    assert len(notes[0].title) <= 255
