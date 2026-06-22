"""Stale-run reconciler — per-run heartbeat (AP-180).

The daemon stamps Run.last_heartbeat_at for every run it reports as in flight.
`reconcile_stale_runs` flips a non-terminal run to FAILED when that clock goes
stale — catching BOTH a dead daemon (it stops reporting all its runs) AND a
dead dispatch whose daemon is still alive (the run never reached the
subprocess, so it's never reported, even though the runtime keeps heartbeating).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.reconciler import (
    STALE_RUN_THRESHOLD_S,
    reconcile_stale_runs,
)
from backend.forge.models import (
    ForgeRuntime, Run, RunStatus, RuntimeStatus,
)
from backend.models import Notification, Profile, Role


@pytest.fixture(autouse=True)
def test_db(pg):
    with bdb.privileged(), bdb.SessionLocal() as db:
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        db.add(Profile(name="admin", account_type="human", roles=[admin_role],
                       org_id=pg.org_id, password_hash=""))
        db.commit()
    yield pg


def _make_run(*, run_heartbeat_age_s: float | None,
              status: RunStatus = RunStatus.RUNNING,
              created_age_s: float = 0.0) -> dict:
    """Create an agent + run. The runtime is ALWAYS fresh (heartbeating now) —
    so these tests exercise the per-RUN clock independently of daemon liveness.
    `run_heartbeat_age_s=None` → the daemon never reported this run; otherwise
    Run.last_heartbeat_at is N seconds in the past. `created_age_s` ages the
    Run row (for the never-reported grace window)."""
    now = datetime.now(timezone.utc)
    with bdb.SessionLocal() as db:
        rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                          status=RuntimeStatus.ONLINE, last_heartbeat=now)
        db.add(rt)
        db.commit()
        rt_id = rt.id
    project = core_services.create_project("P", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(
        agent_id=agent["id"], project_id=project["id"],
    )
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run["id"]).first()
        r.status = status
        r.last_heartbeat_at = (None if run_heartbeat_age_s is None
                               else now - timedelta(seconds=run_heartbeat_age_s))
        if created_age_s:
            r.created_at = now - timedelta(seconds=created_age_s)
        db.commit()
    return {"run_id": run["id"], "agent_id": agent["id"]}


def _admin_notes() -> list[Notification]:
    with bdb.SessionLocal() as db:
        return [n for n in db.query(Notification).all()
                if (p := db.get(Profile, n.profile_id))
                and "admin" in p.role_names]


# ── reconciles stale runs ────────────────────────────────────────────

def test_reconciles_run_with_stale_heartbeat(test_db):
    s = _make_run(run_heartbeat_age_s=STALE_RUN_THRESHOLD_S + 30)
    out = reconcile_stale_runs()
    assert len(out["reconciled"]) == 1
    assert out["reconciled"][0]["run_id"] == s["run_id"]
    r = forge_services.get_run(s["run_id"])
    assert r["status"] == "failed"
    assert "stopped reporting" in (r["error"] or "").lower()
    assert r["outcome"] == "failed"


def test_dead_dispatch_while_daemon_alive_is_reconciled(test_db):
    """The headline fix: the runtime is fresh (still heartbeating) but this
    specific run was never reported in flight — a dispatch that died before
    reaching the subprocess. The per-run clock catches it; the old
    runtime-heartbeat check would have left the spinner up forever."""
    s = _make_run(run_heartbeat_age_s=None,
                  created_age_s=STALE_RUN_THRESHOLD_S + 30)
    out = reconcile_stale_runs()
    assert len(out["reconciled"]) == 1
    assert forge_services.get_run(s["run_id"])["status"] == "failed"


def test_heartbeat_stamps_run_clock_and_keeps_it_alive(test_db):
    """A daemon heartbeat reporting a run in flight stamps its per-run clock,
    so the reconciler leaves it alone even though it was created long ago."""
    s = _make_run(run_heartbeat_age_s=None,
                  created_age_s=STALE_RUN_THRESHOLD_S + 30)
    forge_services.heartbeat_runtimes(
        "d", ["claude"],
        inflight=[{"scope_key": "task:x", "run_id": s["run_id"]}])
    out = reconcile_stale_runs()
    assert out["reconciled"] == []
    assert forge_services.get_run(s["run_id"])["status"] == "running"


def test_reconciler_notifies_admins(test_db):
    _make_run(run_heartbeat_age_s=STALE_RUN_THRESHOLD_S + 30)
    reconcile_stale_runs()
    notes = _admin_notes()
    assert any("heartbeat" in n.title.lower() and "reconciled" in n.title.lower()
               for n in notes), [n.title for n in notes]


def test_reconciler_handles_pending_runs_too(test_db):
    s = _make_run(run_heartbeat_age_s=STALE_RUN_THRESHOLD_S + 30,
                  status=RunStatus.PENDING)
    out = reconcile_stale_runs()
    assert len(out["reconciled"]) == 1
    assert forge_services.get_run(s["run_id"])["status"] == "failed"


# ── leaves fresh runs alone ──────────────────────────────────────────

def test_fresh_run_heartbeat_leaves_run_untouched(test_db):
    """The daemon reported this run a moment ago — don't touch it."""
    s = _make_run(run_heartbeat_age_s=10)  # reported 10s ago
    out = reconcile_stale_runs()
    assert out["reconciled"] == []
    assert forge_services.get_run(s["run_id"])["status"] == "running"


def test_never_reported_young_run_left_untouched(test_db):
    """A run that JUST dispatched, before the daemon's first inflight report,
    must not be killed on the first sweep — the boot window would otherwise
    blow away every fresh dispatch."""
    s = _make_run(run_heartbeat_age_s=None, created_age_s=5)
    out = reconcile_stale_runs()
    assert out["reconciled"] == []


def test_completed_runs_ignored(test_db):
    s = _make_run(run_heartbeat_age_s=STALE_RUN_THRESHOLD_S + 30,
                  status=RunStatus.COMPLETED)
    out = reconcile_stale_runs()
    assert out["reconciled"] == []
    assert forge_services.get_run(s["run_id"])["status"] == "completed"


def test_paused_runs_ignored(test_db):
    """PAUSED is a deliberate user state, not a stuck state."""
    s = _make_run(run_heartbeat_age_s=STALE_RUN_THRESHOLD_S + 30,
                  status=RunStatus.PAUSED)
    out = reconcile_stale_runs()
    assert out["reconciled"] == []
    assert forge_services.get_run(s["run_id"])["status"] == "paused"


# ── idempotent ───────────────────────────────────────────────────────

def test_reconciler_is_idempotent(test_db):
    _make_run(run_heartbeat_age_s=STALE_RUN_THRESHOLD_S + 30)
    first = reconcile_stale_runs()
    second = reconcile_stale_runs()
    assert len(first["reconciled"]) == 1
    assert second["reconciled"] == []
