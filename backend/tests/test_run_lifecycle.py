"""P3: transient run states (PAUSING / CANCELLING / RESUMING).

When the user clicks Stop / Resume, the row is moved to a transient
state immediately (so the UI is honest), and the terminal state lands
only when the daemon confirms. Races between a pending stop and an
auto-resume on chat send are rejected up front. The reconciler escalates
runs that get stuck in a transient state (daemon dropped the frame).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.reconciler import (
    STUCK_TRANSIENT_THRESHOLD_S, reconcile_stale_runs,
)
from backend.forge.models import (
    AgentMessage, ForgeRuntime, MessageRole, Run, RunStatus, RunOutcome,
    RuntimeStatus,
)
from backend.models import Profile, Role


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.reconciler.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        db.add(Profile(name="admin", role_id=admin_role.id, password_hash=""))
        db.commit()
        db.close()
        yield TestSession


def _setup(TestSession) -> dict:
    db = TestSession()
    rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                      status=RuntimeStatus.ONLINE,
                      last_heartbeat=datetime.now(timezone.utc))
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
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run["id"]).first()
        r.status = RunStatus.RUNNING
        db.commit()
    return {"run_id": run["id"], "agent_id": agent["id"],
            "task_id": task["id"]}


# ── pause_run writes PAUSING, not PAUSED ─────────────────────────────

def test_pause_run_writes_pausing_transient(test_db):
    s = _setup(test_db)
    forge_services.pause_run(s["run_id"])
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == s["run_id"]).first()
        assert r.status == RunStatus.PAUSING
        assert r.stop_requested_at is not None


def test_paused_complete_flips_pausing_to_paused(test_db):
    """Daemon trigger-complete(paused=True) is what produces the
    terminal PAUSED state and clears the audit timestamp."""
    s = _setup(test_db)
    forge_services.pause_run(s["run_id"])
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t-p", run_id=s["run_id"],
        success=False, paused=True, session_id="sess-1",
    )
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == s["run_id"]).first()
        assert r.status == RunStatus.PAUSED
        assert r.session_id == "sess-1"
        assert r.stop_requested_at is None


# ── cancel_run writes CANCELLING, not CANCELLED ──────────────────────

def test_cancel_run_writes_cancelling_transient(test_db):
    s = _setup(test_db)
    forge_services.cancel_run(s["run_id"])
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == s["run_id"]).first()
        assert r.status == RunStatus.CANCELLING
        assert r.stop_requested_at is not None


def test_cancelled_complete_flips_cancelling_to_cancelled(test_db):
    s = _setup(test_db)
    forge_services.cancel_run(s["run_id"])
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t-c", run_id=s["run_id"],
        success=False, error="Cancelled by user.", cancelled=True,
    )
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == s["run_id"]).first()
        assert r.status == RunStatus.CANCELLED
        assert r.stop_requested_at is None


def test_cancel_on_cancelling_run_is_idempotent(test_db):
    """Second click on Cancel while the first is in flight is rejected
    cleanly — no duplicate state writes, no double WS frames."""
    s = _setup(test_db)
    forge_services.cancel_run(s["run_id"])
    res = forge_services.cancel_run(s["run_id"])
    assert "already" in (res.get("error") or "").lower()


# ── auto-resume race protection ──────────────────────────────────────

def test_send_message_into_pausing_scope_is_rejected(test_db):
    """A user message into a PAUSING scope must not silently spawn a
    second proc. Reject and ask the user to retry."""
    s = _setup(test_db)
    forge_services.pause_run(s["run_id"])  # → PAUSING
    res = forge_services.send_runtime_message(
        s["agent_id"], content="hello",
        scope_key=f"task:{s['task_id']}",
    )
    assert "pausing" in (res.get("error") or "").lower()


def test_send_message_into_cancelling_scope_is_rejected(test_db):
    s = _setup(test_db)
    forge_services.cancel_run(s["run_id"])  # → CANCELLING
    res = forge_services.send_runtime_message(
        s["agent_id"], content="hello",
        scope_key=f"task:{s['task_id']}",
    )
    assert "cancelling" in (res.get("error") or "").lower()


def test_send_message_into_paused_scope_resumes_to_running(test_db):
    """PAUSED is confirmed-terminated — auto-resume goes straight to
    RUNNING (no transient — there's no race here)."""
    s = _setup(test_db)
    # Get into PAUSED via the daemon-ack path.
    forge_services.pause_run(s["run_id"])
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t-p", run_id=s["run_id"],
        success=False, paused=True,
    )
    forge_services.send_runtime_message(
        s["agent_id"], content="continue please",
        scope_key=f"task:{s['task_id']}",
    )
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == s["run_id"]).first()
        assert r.status == RunStatus.RUNNING


# ── reconciler escalates stuck transients ────────────────────────────

def _make_transient(TestSession, status: RunStatus, *, age_s: float) -> str:
    s = _setup(TestSession)
    now = datetime.now(timezone.utc)
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == s["run_id"]).first()
        r.status = status
        r.stop_requested_at = now - timedelta(seconds=age_s)
        db.commit()
    return s["run_id"]


def test_reconciler_escalates_stuck_pausing_to_paused(test_db):
    rid = _make_transient(test_db, RunStatus.PAUSING,
                          age_s=STUCK_TRANSIENT_THRESHOLD_S + 5)
    out = reconcile_stale_runs()
    assert any(e["run_id"] == rid and e["to"] == "paused"
               for e in out["escalated"])
    assert forge_services.get_run(rid)["status"] == "paused"


def test_reconciler_escalates_stuck_cancelling_to_cancelled(test_db):
    rid = _make_transient(test_db, RunStatus.CANCELLING,
                          age_s=STUCK_TRANSIENT_THRESHOLD_S + 5)
    out = reconcile_stale_runs()
    assert any(e["run_id"] == rid and e["to"] == "cancelled"
               for e in out["escalated"])
    assert forge_services.get_run(rid)["status"] == "cancelled"


def test_reconciler_escalates_stuck_resuming_to_failed(test_db):
    """RESUMING never resolving means the daemon didn't pick up the
    dispatch — that's a real failure, not a quiet retry."""
    rid = _make_transient(test_db, RunStatus.RESUMING,
                          age_s=STUCK_TRANSIENT_THRESHOLD_S + 5)
    out = reconcile_stale_runs()
    assert any(e["run_id"] == rid and e["to"] == "failed"
               for e in out["escalated"])
    r = forge_services.get_run(rid)
    assert r["status"] == "failed"
    assert "resume" in (r["error"] or "").lower()


def test_reconciler_leaves_fresh_transients_alone(test_db):
    """A pause that landed a moment ago must not be escalated — the
    daemon's confirmation could still be in flight."""
    rid = _make_transient(test_db, RunStatus.PAUSING, age_s=2)
    out = reconcile_stale_runs()
    assert out["escalated"] == []
    assert forge_services.get_run(rid)["status"] == "pausing"
