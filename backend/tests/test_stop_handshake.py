"""P1: daemon -> backend cancel handshake.

When the user presses Stop, the daemon kills the subprocess and posts
`trigger-complete(cancelled=True)`. Backend must:
  - flip the run to CANCELLED (not FAILED),
  - leave a "Run cancelled by user." summary,
  - NOT post the "⚠ execution failed" admin notification,
  - NOT post the failure system message on the chat thread.

Symmetric with the existing `paused=True` branch.
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
from backend.forge.models import (
    AgentMessage, ForgeRuntime, MessageRole, Run, RunStatus, RuntimeStatus,
)
from backend.models import Notification, Profile, Role


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.runs.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        # _notify_admins (used by the FAILED path we want to NOT fire)
        # needs a real admin profile to land its rows on.
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        db.add(Profile(name="admin", role_id=admin_role.id, password_hash=""))
        db.commit()
        db.close()
        yield TestSession


def _make_run(TestSession) -> dict:
    db = TestSession()
    rt = ForgeRuntime(daemon_id="d", provider="claude",
                      binary_path="/tmp/c", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "T", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(
        agent_id=agent["id"], task_id=task["id"], project_id=project["id"],
    )
    # Promote to RUNNING so cancel is a meaningful transition.
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run["id"]).first()
        r.status = RunStatus.RUNNING
        db.commit()
    return {"run_id": run["id"], "agent_id": agent["id"]}


def _admin_notes(TestSession) -> list[Notification]:
    db = TestSession()
    try:
        return (db.query(Notification)
                  .join(Profile, Notification.profile_id == Profile.id)
                  .join(Role, Profile.role_id == Role.id)
                  .filter(Role.name == "admin")
                  .all())
    finally:
        db.close()


# ── happy path ────────────────────────────────────────────────────────

def test_cancelled_complete_flips_run_to_cancelled(test_db):
    s = _make_run(test_db)
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="tc1", run_id=s["run_id"],
        success=False, error="Cancelled by user.", cancelled=True,
    )
    r = forge_services.get_run(s["run_id"])
    assert r["status"] == "cancelled", r["status"]
    assert "cancelled" in (r["summary"] or "").lower()


def test_cancelled_complete_does_not_notify_admins(test_db):
    """A user-initiated cancel is not a failure — no admin alert."""
    s = _make_run(test_db)
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="tc2", run_id=s["run_id"],
        success=False, error="Cancelled by user.", cancelled=True,
    )
    assert _admin_notes(test_db) == []


def test_cancelled_complete_drops_no_failure_chat_message(test_db):
    """The 'execution failed' system message must NOT land in the chat
    thread on a clean cancel."""
    s = _make_run(test_db)
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="tc3", run_id=s["run_id"],
        success=False, error="Cancelled by user.", cancelled=True,
    )
    with forge_services._session() as db:
        sys_msgs = (db.query(AgentMessage)
                      .filter(AgentMessage.agent_id == s["agent_id"],
                              AgentMessage.role == MessageRole.SYSTEM)
                      .all())
    assert sys_msgs == []


def test_cancelled_complete_persists_token_counters(test_db):
    s = _make_run(test_db)
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="tc4", run_id=s["run_id"],
        success=False, input_tokens=120, output_tokens=80,
        error="Cancelled by user.", cancelled=True,
    )
    r = forge_services.get_run(s["run_id"])
    assert r["input_tokens"] == 120
    assert r["output_tokens"] == 80


# ── symmetry checks ──────────────────────────────────────────────────

def test_normal_failure_still_notifies_admins(test_db):
    """Sanity: without `cancelled=True`, a non-zero exit still produces
    the admin notification we expect on real failures."""
    s = _make_run(test_db)
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="tc5", run_id=s["run_id"],
        success=False, error="subprocess exited with code 1",
    )
    notes = _admin_notes(test_db)
    assert any("run failed" in n.title.lower() for n in notes)


def test_paused_branch_still_keeps_run_paused(test_db):
    """The cancelled branch sits *before* the paused branch — make sure
    paused still wins for paused=True calls (regression guard)."""
    s = _make_run(test_db)
    forge_services._TRACE_SCOPE["tc6"] = f"task:{s['run_id'][:8]}"
    try:
        forge_services.complete_trigger(
            agent_id=s["agent_id"], trace_id="tc6", run_id=s["run_id"],
            success=False, paused=True, session_id="sess-x",
        )
    finally:
        forge_services._TRACE_SCOPE.pop("tc6", None)
    r = forge_services.get_run(s["run_id"])
    assert r["status"] == "running" or r["status"] == "paused"
    # The paused branch never changes status — it only persists session_id.
    # The pre-cancel status was RUNNING; that stands until the (separate)
    # `pause_run` path writes PAUSED.
