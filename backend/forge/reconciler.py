"""P2: stale-run reconciler — kill RUNNING rows whose daemon is gone.

A daemon that crashes (machine off, SIGKILL, network gone) leaves the
Run row pinned at PENDING/RUNNING forever. Nothing ever posts
trigger-complete, so `complete_trigger` never fires. The UI shows the
run as live indefinitely; the agent appears stuck.

This module periodically sweeps for that case: any non-terminal run
whose agent's runtime hasn't heartbeated in `STALE_RUN_THRESHOLD_S` is
flipped to FAILED with a clear error. The sweep is idempotent — a
second pass finds nothing.

Scheduled from `backend.forge.scheduler` every `RECONCILE_INTERVAL_S`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.db import SessionLocal
from backend.forge.models import (
    Run, RunStatus, RunOutcome,
)
from backend.forge.services import _notify_admins, _broadcast_status

logger = logging.getLogger("agentira.forge.reconciler")

# How often the scheduler fires the sweep.
RECONCILE_INTERVAL_S = 30
# How long without a heartbeat before we assume the daemon is gone.
# Heartbeat cadence is well under a minute; 120s gives enough slack for
# transient network blips without holding zombie runs for too long.
STALE_RUN_THRESHOLD_S = 120
# How long a run can sit in INTERRUPTING before we assume the daemon dropped
# the frame and force the terminal state (PAUSED for intent=pause, CANCELLED
# for intent=discard). The daemon's SIGTERM→SIGKILL window is ~5s; 30s gives
# generous slack while still feeling responsive.
STUCK_TRANSIENT_THRESHOLD_S = 30


def _utc(dt: datetime | None) -> datetime | None:
    """tz-naive timestamps slip in from SQLite — coerce to UTC for math."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def reconcile_stale_runs() -> dict:
    """Sweep non-terminal runs whose daemon hasn't checked in. Returns
    a summary suitable for logging / a future status endpoint."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=STALE_RUN_THRESHOLD_S)
    transient_cutoff = now - timedelta(seconds=STUCK_TRANSIENT_THRESHOLD_S)
    reconciled: list[dict] = []
    escalated: list[dict] = []

    with SessionLocal() as db:
        # Escalate stuck INTERRUPTING rows first — these resolve fast in the
        # happy path, so anything past the threshold means the daemon didn't
        # ack and we pick the terminal state from interrupt_intent.
        stuck = (db.query(Run)
                   .filter(Run.status == RunStatus.INTERRUPTING)
                   .filter(Run.stop_requested_at.isnot(None))
                   .filter(Run.stop_requested_at <= transient_cutoff)
                   .all())
        for run in stuck:
            prior = run.status
            if run.interrupt_intent == "discard":
                run.status = RunStatus.CANCELLED
                run.finished_at = now
                if run.outcome is None:
                    run.outcome = RunOutcome.FAILED
            else:  # "pause" (default) — SIGKILL has run; treat as paused
                run.status = RunStatus.PAUSED
            run.stop_requested_at = None
            run.interrupt_intent = None
            escalated.append({"run_id": run.id, "from": prior.value,
                              "to": run.status.value})
            _broadcast_status(run.id, run.status)
        if escalated:
            db.commit()
            logger.warning("Reconciler escalated %d stuck transient(s): %s",
                           len(escalated), escalated)
        # Per-run liveness: the daemon stamps Run.last_heartbeat_at for every
        # run it reports as in flight (services.heartbeat_runtimes). A
        # non-terminal run the daemon stops reporting goes stale here and is
        # failed — even if the daemon itself is still alive (the dead-dispatch
        # case: a dispatch that never reached the subprocess). last_heartbeat_at
        # is persisted, so a backend restart doesn't reset it — the next
        # heartbeat (~5s) re-stamps live runs before this threshold elapses.
        rows = (db.query(Run)
                  .filter(Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING]))
                  .all())

        for run in rows:
            rhb = _utc(run.last_heartbeat_at)
            created = _utc(run.created_at) or now
            if rhb is None:
                # The daemon hasn't reported this run yet. Grace window from
                # creation so a just-dispatched run (and test fixtures that
                # never heartbeat) aren't failed instantly.
                if (now - created).total_seconds() < STALE_RUN_THRESHOLD_S:
                    continue
            elif rhb >= cutoff:
                continue  # daemon reported this run recently — it's alive

            run.status = RunStatus.FAILED
            run.finished_at = now
            if run.outcome is None:
                run.outcome = RunOutcome.FAILED
            run.error = "Run reconciled as failed — daemon stopped reporting it."
            _broadcast_status(run.id, RunStatus.FAILED)
            agent_name = run.agent.name if run.agent else "agent"
            _notify_admins(
                db,
                type_="forge.run.failed",
                title=f"{agent_name} run reconciled (no daemon heartbeat)",
                link=f"/forge/runs/{run.id}",
            )
            reconciled.append({
                "run_id": run.id,
                "agent_id": run.agent_id,
                "last_heartbeat": rhb.isoformat() if rhb else None,
            })

        if reconciled:
            db.commit()
            logger.warning(
                "Reconciler flipped %d stale run(s) to FAILED: %s",
                len(reconciled), [r["run_id"] for r in reconciled],
            )

    return {"reconciled": reconciled, "escalated": escalated,
            "at": now.isoformat()}
