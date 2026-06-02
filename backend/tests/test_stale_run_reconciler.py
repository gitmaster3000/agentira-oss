"""P2: stale-run reconciler — catches daemon-crash orphans.

A daemon that dies mid-run leaves the Run row pinned at RUNNING/PENDING
forever. `reconcile_stale_runs` sweeps and flips them to FAILED with a
clear error when the agent's runtime has had no heartbeat for
STALE_RUN_THRESHOLD_S.
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
    STALE_RUN_THRESHOLD_S,
    reconcile_stale_runs,
)
from backend.forge.models import (
    ForgeRuntime, Run, RunStatus, RunOutcome, RuntimeStatus,
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
         patch("backend.forge.runs.SessionLocal", TestSession), \
         patch("backend.forge.reconciler.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        db.add(Profile(name="admin", role_id=admin_role.id, password_hash=""))
        db.commit()
        db.close()
        yield TestSession


def _make_run(TestSession, *, heartbeat_age_s: float | None,
              status: RunStatus = RunStatus.RUNNING,
              created_age_s: float = 0.0) -> dict:
    """Create an agent + run. `heartbeat_age_s=None` → runtime never
    heartbeated; otherwise the runtime row's last_heartbeat is N seconds
    in the past. `created_age_s` ages the Run row similarly."""
    now = datetime.now(timezone.utc)
    db = TestSession()
    hb = None if heartbeat_age_s is None else now - timedelta(seconds=heartbeat_age_s)
    rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                      status=RuntimeStatus.ONLINE, last_heartbeat=hb)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    project = core_services.create_project("P", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(
        agent_id=agent["id"], project_id=project["id"],
    )
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run["id"]).first()
        r.status = status
        if created_age_s:
            r.created_at = now - timedelta(seconds=created_age_s)
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


# ── reconciles stale runs ────────────────────────────────────────────

def test_reconciles_run_with_dead_daemon(test_db):
    s = _make_run(test_db, heartbeat_age_s=STALE_RUN_THRESHOLD_S + 30)
    out = reconcile_stale_runs()
    assert len(out["reconciled"]) == 1
    assert out["reconciled"][0]["run_id"] == s["run_id"]
    r = forge_services.get_run(s["run_id"])
    assert r["status"] == "failed"
    assert "daemon offline" in (r["error"] or "").lower()
    assert r["outcome"] == "failed"


def test_reconciler_notifies_admins(test_db):
    s = _make_run(test_db, heartbeat_age_s=STALE_RUN_THRESHOLD_S + 30)
    reconcile_stale_runs()
    notes = _admin_notes(test_db)
    assert any("offline" in n.title.lower() and "reconciled" in n.title.lower()
               for n in notes), [n.title for n in notes]


def test_reconciler_handles_pending_runs_too(test_db):
    s = _make_run(test_db, heartbeat_age_s=STALE_RUN_THRESHOLD_S + 30,
                  status=RunStatus.PENDING)
    out = reconcile_stale_runs()
    assert len(out["reconciled"]) == 1
    assert forge_services.get_run(s["run_id"])["status"] == "failed"


# ── leaves fresh runs alone ──────────────────────────────────────────

def test_fresh_heartbeat_leaves_run_untouched(test_db):
    """Daemon checked in recently — don't touch the run."""
    s = _make_run(test_db, heartbeat_age_s=10)  # 10s ago
    out = reconcile_stale_runs()
    assert out["reconciled"] == []
    assert forge_services.get_run(s["run_id"])["status"] == "running"


def test_never_heartbeated_young_run_left_untouched(test_db):
    """A run that JUST started against a runtime which hasn't sent its
    first heartbeat yet must not be killed on the first sweep — the
    boot window would otherwise blow away every fresh dispatch."""
    s = _make_run(test_db, heartbeat_age_s=None, created_age_s=5)
    out = reconcile_stale_runs()
    assert out["reconciled"] == []


def test_never_heartbeated_old_run_reconciled(test_db):
    """A run created longer ago than the threshold whose runtime has
    never heartbeated → the daemon clearly isn't coming. Reconcile it."""
    s = _make_run(test_db, heartbeat_age_s=None,
                  created_age_s=STALE_RUN_THRESHOLD_S + 30)
    out = reconcile_stale_runs()
    assert len(out["reconciled"]) == 1


def test_completed_runs_ignored(test_db):
    """Reconciler scopes to non-terminal statuses. A long-finished run
    must not be touched."""
    s = _make_run(test_db, heartbeat_age_s=STALE_RUN_THRESHOLD_S + 30,
                  status=RunStatus.COMPLETED)
    out = reconcile_stale_runs()
    assert out["reconciled"] == []
    assert forge_services.get_run(s["run_id"])["status"] == "completed"


def test_paused_runs_ignored(test_db):
    """PAUSED is a deliberate user state, not a stuck state."""
    s = _make_run(test_db, heartbeat_age_s=STALE_RUN_THRESHOLD_S + 30,
                  status=RunStatus.PAUSED)
    out = reconcile_stale_runs()
    assert out["reconciled"] == []
    assert forge_services.get_run(s["run_id"])["status"] == "paused"


# ── idempotent ───────────────────────────────────────────────────────

def test_reconciler_is_idempotent(test_db):
    """Running twice in a row finds nothing the second time."""
    _make_run(test_db, heartbeat_age_s=STALE_RUN_THRESHOLD_S + 30)
    first = reconcile_stale_runs()
    second = reconcile_stale_runs()
    assert len(first["reconciled"]) == 1
    assert second["reconciled"] == []
