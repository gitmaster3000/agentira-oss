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
    Agent, ForgeRuntime, Run, RunStatus, RunOutcome,
)
from backend.forge.services import _notify_admins

logger = logging.getLogger("agentira.forge.reconciler")

# How often the scheduler fires the sweep.
RECONCILE_INTERVAL_S = 30
# How long without a heartbeat before we assume the daemon is gone.
# Heartbeat cadence is well under a minute; 120s gives enough slack for
# transient network blips without holding zombie runs for too long.
STALE_RUN_THRESHOLD_S = 120


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
    reconciled: list[dict] = []

    with SessionLocal() as db:
        # Join Run → Agent → ForgeRuntime in one query so we can compute
        # staleness without N+1.
        rows = (db.query(Run, ForgeRuntime)
                  .join(Agent, Run.agent_id == Agent.id)
                  .outerjoin(ForgeRuntime, Agent.runtime_id == ForgeRuntime.id)
                  .filter(Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING]))
                  .all())

        for run, runtime in rows:
            hb = _utc(runtime.last_heartbeat) if runtime else None
            # No runtime row or no heartbeat ever AND the run is older
            # than the threshold → reconcile. Otherwise the test
            # fixtures (which never heartbeat) would have everything
            # marked failed instantly.
            created = _utc(run.created_at) or now
            if hb is None:
                if (now - created).total_seconds() < STALE_RUN_THRESHOLD_S:
                    continue
            elif hb >= cutoff:
                continue  # daemon is fresh — leave it alone

            run.status = RunStatus.FAILED
            run.finished_at = now
            if run.outcome is None:
                run.outcome = RunOutcome.FAILED
            run.error = "Daemon offline — run reconciled as failed."
            agent_name = run.agent.name if run.agent else "agent"
            _notify_admins(
                db,
                type_="forge.run.failed",
                title=f"{agent_name} run reconciled (daemon offline)",
                link=f"/forge/runs/{run.id}",
            )
            reconciled.append({
                "run_id": run.id,
                "agent_id": run.agent_id,
                "last_heartbeat": hb.isoformat() if hb else None,
            })

        if reconciled:
            db.commit()
            logger.warning(
                "Reconciler flipped %d stale run(s) to FAILED: %s",
                len(reconciled), [r["run_id"] for r in reconciled],
            )

    return {"reconciled": reconciled, "at": now.isoformat()}
