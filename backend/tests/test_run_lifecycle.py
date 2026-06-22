"""Transient run state: the single INTERRUPTING state (AP-177 / AP-179).

When the user clicks Stop or Discard, the row moves to INTERRUPTING immediately
(so the UI is honest), with interrupt_intent recording where it lands —
"pause" → PAUSED, "discard" → CANCELLED. The terminal state arrives only when
the daemon confirms. A message into an INTERRUPTING scope is rejected (it would
race the kill). The reconciler escalates a run stuck in INTERRUPTING using its
intent (daemon dropped the frame).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.reconciler import (
    STUCK_TRANSIENT_THRESHOLD_S, reconcile_stale_runs,
)
from backend.forge.models import (
    ForgeRuntime, Run, RunStatus, RuntimeStatus,
)
from backend.models import Profile, Role


@pytest.fixture(autouse=True)
def test_db(pg):
    with bdb.privileged(), bdb.SessionLocal() as db:
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        db.add(Profile(name="admin", account_type="human", roles=[admin_role],
                       org_id=pg.org_id, password_hash=""))
        db.commit()
    yield pg


def _setup() -> dict:
    with bdb.SessionLocal() as db:
        rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                          status=RuntimeStatus.ONLINE,
                          last_heartbeat=datetime.now(timezone.utc))
        db.add(rt)
        db.commit()
        rt_id = rt.id
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


# ── pause / cancel write INTERRUPTING (with intent), not the terminal ────

def test_pause_run_writes_interrupting_pause(test_db):
    s = _setup()
    forge_services.pause_run(s["run_id"])
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == s["run_id"]).first()
        assert r.status == RunStatus.INTERRUPTING
        assert r.interrupt_intent == "pause"
        assert r.stop_requested_at is not None


def test_paused_complete_flips_interrupting_to_paused(test_db):
    """Daemon trigger-complete(paused=True) produces the terminal PAUSED state
    and clears the audit timestamp + intent."""
    s = _setup()
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
        assert r.interrupt_intent is None


def test_cancel_run_writes_interrupting_discard(test_db):
    s = _setup()
    forge_services.cancel_run(s["run_id"])
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == s["run_id"]).first()
        assert r.status == RunStatus.INTERRUPTING
        assert r.interrupt_intent == "discard"
        assert r.stop_requested_at is not None


def test_cancelled_complete_flips_interrupting_to_cancelled(test_db):
    s = _setup()
    forge_services.cancel_run(s["run_id"])
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t-c", run_id=s["run_id"],
        success=False, error="Cancelled by user.", cancelled=True,
    )
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == s["run_id"]).first()
        assert r.status == RunStatus.CANCELLED
        assert r.stop_requested_at is None
        assert r.interrupt_intent is None


def test_cancel_on_interrupting_run_is_idempotent(test_db):
    """Second click on Discard while the first is in flight is rejected
    cleanly — no duplicate state writes, no double WS frames."""
    s = _setup()
    forge_services.cancel_run(s["run_id"])
    res = forge_services.cancel_run(s["run_id"])
    assert "already" in (res.get("error") or "").lower()


# ── send-message-during-interrupt race protection ────────────────────────

def test_send_message_into_interrupting_scope_is_rejected(test_db):
    """A user message into an INTERRUPTING scope must not silently spawn a
    second proc. Reject and ask the user to retry."""
    s = _setup()
    forge_services.pause_run(s["run_id"])  # → INTERRUPTING
    res = forge_services.send_runtime_message(
        s["agent_id"], content="hello",
        scope_key=f"task:{s['task_id']}",
    )
    assert "interrupting" in (res.get("error") or "").lower()


def test_send_message_into_paused_scope_resumes_to_running(test_db):
    """PAUSED is confirmed-terminated — auto-resume goes straight to RUNNING."""
    s = _setup()
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


# ── reconciler escalates a stuck INTERRUPTING by intent ──────────────────

def _make_interrupting(intent: str, *, age_s: float) -> str:
    s = _setup()
    now = datetime.now(timezone.utc)
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == s["run_id"]).first()
        r.status = RunStatus.INTERRUPTING
        r.interrupt_intent = intent
        r.stop_requested_at = now - timedelta(seconds=age_s)
        db.commit()
    return s["run_id"]


def test_reconciler_escalates_stuck_pause_to_paused(test_db):
    rid = _make_interrupting("pause",
                             age_s=STUCK_TRANSIENT_THRESHOLD_S + 5)
    out = reconcile_stale_runs()
    assert any(e["run_id"] == rid and e["to"] == "paused"
               for e in out["escalated"])
    assert forge_services.get_run(rid)["status"] == "paused"


def test_reconciler_escalates_stuck_discard_to_cancelled(test_db):
    rid = _make_interrupting("discard",
                             age_s=STUCK_TRANSIENT_THRESHOLD_S + 5)
    out = reconcile_stale_runs()
    assert any(e["run_id"] == rid and e["to"] == "cancelled"
               for e in out["escalated"])
    assert forge_services.get_run(rid)["status"] == "cancelled"


def test_reconciler_leaves_fresh_interrupting_alone(test_db):
    """A stop that landed a moment ago must not be escalated — the daemon's
    confirmation could still be in flight."""
    rid = _make_interrupting("pause", age_s=2)
    out = reconcile_stale_runs()
    assert out["escalated"] == []
    assert forge_services.get_run(rid)["status"] == "interrupting"
