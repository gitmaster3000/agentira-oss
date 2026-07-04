"""AP-371 — dispatch liveness stamps + reconciler resurrection.

The stale-run reconciler judges a run by Run.last_heartbeat_at with a
grace window keyed on created_at. Three paths used to (re)enter
PENDING/RUNNING without refreshing that clock — sticky-run reuse
(retry), runs.start on a prepared READY run dispatched minutes after
creation, and resume — so the sweep killed the new turn before the
daemon's first report. And once flipped to FAILED, nothing reversed the
verdict even while the daemon kept reporting the run alive: the run
executed and finished while the UI showed a dead run forever.

Covers: (a) start()/reuse stamp last_heartbeat_at so a fresh dispatch
survives the sweep; (b) heartbeat_runtimes resurrects a
reconciler-failed run its daemon reports in flight; (c) resurrection
matches ONLY the reconciler's verdict — real failures stay terminal.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge import runs as forge_runs
from backend.forge.reconciler import reconcile_stale_runs
from backend.forge.models import (
    Run, RunStatus, RunOutcome, ForgeRuntime, RuntimeStatus,
)


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.runs.SessionLocal", TestSession), \
         patch("backend.forge.reconciler.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


LONG_AGO = datetime.now(timezone.utc) - timedelta(minutes=10)


def _make_run(test_db, daemon_id: str = "d1") -> str:
    db = test_db()
    rt = ForgeRuntime(daemon_id=daemon_id, provider="claude",
                      binary_path="/tmp/c", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()

    project = core_services.create_project("AP371 Project", actor="system")
    task = core_services.create_task(project["id"], "AP371 Task", actor="system")
    agent = forge_services.create_agent(name="AP371 Agent", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(
        agent_id=agent["id"], task_id=task["id"], project_id=project["id"],
    )
    return run["id"]


def _age_run(test_db, run_id: str, *, status: RunStatus,
             heartbeat: datetime | None, created: datetime = LONG_AGO) -> None:
    """Force a run into the pre-fix danger shape: old row, stale/no clock."""
    db = test_db()
    r = db.query(Run).filter(Run.id == run_id).first()
    r.status = status
    r.created_at = created
    r.last_heartbeat_at = heartbeat
    db.commit()
    db.close()


def _get(test_db, run_id: str) -> Run:
    db = test_db()
    r = db.query(Run).filter(Run.id == run_id).first()
    db.expunge(r)
    db.close()
    return r


# ── Baseline: the sweep still catches genuinely dead runs ──────────────

def test_reconciler_fails_stale_run_without_heartbeat(test_db):
    rid = _make_run(test_db)
    _age_run(test_db, rid, status=RunStatus.RUNNING, heartbeat=None)
    reconcile_stale_runs()
    r = _get(test_db, rid)
    assert r.status == RunStatus.FAILED
    assert r.error == forge_runs.RECONCILED_ERROR


# ── Liveness stamps on (re)entry to a live state ────────────────────────

def test_start_stamps_liveness_so_old_ready_run_survives_sweep(test_db):
    """A READY run dispatched minutes after prepare: start() must re-arm
    the clock or the very next sweep kills it (the AP-370/AP-373 case)."""
    rid = _make_run(test_db)
    _age_run(test_db, rid, status=RunStatus.PENDING, heartbeat=None)
    forge_runs.start(rid)
    r = _get(test_db, rid)
    assert r.status == RunStatus.RUNNING
    assert r.last_heartbeat_at is not None
    reconcile_stale_runs()
    assert _get(test_db, rid).status == RunStatus.RUNNING


def test_sticky_reuse_stamps_liveness(test_db):
    """Retry re-arms the same row (AP-190 sticky run): the previous life's
    stale heartbeat must not carry over into the new turn."""
    rid = _make_run(test_db)
    _age_run(test_db, rid, status=RunStatus.FAILED, heartbeat=LONG_AGO)
    db = test_db()
    r = db.query(Run).filter(Run.id == rid).first()
    reused = forge_runs.get_or_create_task_run(
        db, agent_id=r.agent_id, task_id=r.task_id, project_id=r.project_id,
    )
    db.commit()
    db.close()
    assert reused == rid  # same sticky row, not a second run
    reconcile_stale_runs()
    assert _get(test_db, rid).status == RunStatus.RUNNING


# ── Resurrection: daemon report is proof of life ────────────────────────

def test_heartbeat_resurrects_reconciler_failed_run(test_db):
    rid = _make_run(test_db, daemon_id="d-res")
    _age_run(test_db, rid, status=RunStatus.RUNNING, heartbeat=None)
    reconcile_stale_runs()
    r = _get(test_db, rid)
    assert r.status == RunStatus.FAILED
    assert r.outcome == RunOutcome.FAILED  # reconciler's stamp

    forge_services.heartbeat_runtimes(
        "d-res", ["claude"], inflight=[{"run_id": rid}])

    r = _get(test_db, rid)
    assert r.status == RunStatus.RUNNING
    assert r.error is None
    assert r.finished_at is None
    assert r.outcome is None  # agent's verdict comes later via finish_run
    assert r.last_heartbeat_at is not None


def test_heartbeat_does_not_resurrect_real_failures(test_db):
    """Only the reconciler's exact verdict is reversible. A run that failed
    for a real reason must stay failed even if its id shows up in an
    inflight report (e.g. a confused daemon)."""
    rid = _make_run(test_db, daemon_id="d-real")
    db = test_db()
    r = db.query(Run).filter(Run.id == rid).first()
    r.status = RunStatus.FAILED
    r.error = "process exited 1"
    r.outcome = RunOutcome.FAILED
    db.commit()
    db.close()

    forge_services.heartbeat_runtimes(
        "d-real", ["claude"], inflight=[{"run_id": rid}])

    r = _get(test_db, rid)
    assert r.status == RunStatus.FAILED
    assert r.error == "process exited 1"
