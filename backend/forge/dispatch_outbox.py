"""Durable dispatch outbox (AP-390).

Every daemon-bound WS frame is persisted as a DispatchIntent row before
any send attempt. Frames used to live only in the sending process's
WsHub — but the hub is a per-process singleton, and finish_run (and so
workflow.advance_after_run) executes in the flowty-mcp process, whose
hub never holds the daemon's WS socket. Those dispatches queued into a
dead in-memory dict and expired silently: lost reviewer hand-offs, lost
integrate merges, lost corrective bounces (prod incident 2026-07-04).

Rows are the source of truth (ADR-007 spirit); delivery paths:
  1. Fast path — the writing process's hub has the runtime connected:
     send immediately, mark delivered.
  2. flowty-api delivery loop — `deliver_pending()` on the scheduler
     tick sends pending rows through the api process's hub.
  3. Daemon (re)connect — `WsHub._deliver_pending` redelivers pending
     rows for the connecting daemon's runtimes.
Delivery is at-least-once: the daemon dedups frames by event_id and its
durable inflight registry keys one live turn per scope.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from backend.db import SessionLocal
from backend.forge.models import DispatchIntent

logger = logging.getLogger("agentira.forge.dispatch_outbox")

# A pending intent older than this with no daemon reconnect is failed and
# surfaced (same TTL the in-memory redelivery queue used, see ws_dispatch).
def _ttl_s() -> float:
    from backend.forge.ws_dispatch import DISPATCH_REDELIVER_TTL_S
    return DISPATCH_REDELIVER_TTL_S


def write_intent(*, kind: str, event_id: str, runtime_id: str,
                 payload: dict, agent_id: str = "", run_id: str = "",
                 task_id: str = "") -> str | None:
    """Persist a frame as a pending intent. Returns the intent id, or
    None when the write fails (caller falls back to fire-and-forget —
    a DB outage must not make dispatch worse than it was before)."""
    try:
        with SessionLocal() as db:
            row = DispatchIntent(
                kind=kind, event_id=event_id, runtime_id=runtime_id,
                agent_id=agent_id, run_id=run_id, task_id=task_id,
                payload_json=json.dumps(payload),
            )
            db.add(row)
            db.commit()
            return row.id
    except Exception as exc:  # noqa: BLE001 — durability is best-effort
        logger.warning("outbox write failed (%s %s): %s", kind, event_id, exc)
        return None


def mark_delivered(intent_id: str | None) -> None:
    if not intent_id:
        return
    try:
        with SessionLocal() as db:
            (db.query(DispatchIntent)
               .filter(DispatchIntent.id == intent_id,
                       DispatchIntent.status == "pending")
               .update({DispatchIntent.status: "delivered",
                        DispatchIntent.delivered_at: datetime.now(timezone.utc)},
                       synchronize_session=False))
            db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("outbox mark_delivered failed (%s): %s", intent_id, exc)


def pending_for_runtimes(runtime_ids: set[str] | list[str]) -> list[dict]:
    """Pending intents for the given runtimes, oldest first — what a
    daemon (re)connect must redeliver."""
    ids = list(runtime_ids)
    if not ids:
        return []
    try:
        with SessionLocal() as db:
            rows = (db.query(DispatchIntent)
                      .filter(DispatchIntent.status == "pending",
                              DispatchIntent.runtime_id.in_(ids))
                      .order_by(DispatchIntent.created_at.asc())
                      .all())
            return [_row_view(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("outbox pending_for_runtimes failed: %s", exc)
        return []


def _row_view(r: DispatchIntent) -> dict:
    try:
        payload = json.loads(r.payload_json or "{}")
    except Exception:  # noqa: BLE001
        payload = {}
    return {"id": r.id, "kind": r.kind, "event_id": r.event_id,
            "runtime_id": r.runtime_id, "agent_id": r.agent_id,
            "run_id": r.run_id, "task_id": r.task_id,
            "created_at": r.created_at, "attempts": r.attempts,
            "payload": payload}


async def deliver_pending() -> dict:
    """One delivery sweep: send every pending intent whose runtime has a
    connected daemon on THIS process's hub; fail (visibly) any intent
    older than the TTL with still no daemon. Runs on the flowty-api
    scheduler tick — the api process is the one holding daemon sockets."""
    from backend.forge.ws_dispatch import hub

    delivered = 0
    failed = 0
    try:
        with SessionLocal() as db:
            rows = (db.query(DispatchIntent)
                      .filter(DispatchIntent.status == "pending")
                      .order_by(DispatchIntent.created_at.asc())
                      .limit(200)
                      .all())
            views = [_row_view(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("outbox sweep query failed: %s", exc)
        return {"delivered": 0, "failed": 0, "error": str(exc)}

    now = datetime.now(timezone.utc)
    for v in views:
        conns = [c for c in hub._conns.values()
                 if v["runtime_id"] in c.runtime_ids]
        if conns:
            try:
                for conn in conns:
                    await conn.send(v["event_id"], v["payload"])
                mark_delivered(v["id"])
                delivered += 1
                logger.info("outbox delivered %s %s run=%s task=%s → daemon",
                            v["kind"], v["event_id"], v["run_id"] or "-",
                            v["task_id"] or "-")
            except Exception as exc:  # noqa: BLE001
                _bump_attempts(v["id"], str(exc))
            continue
        created = v["created_at"]
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created is not None and (now - created).total_seconds() > _ttl_s():
            try:
                _fail_intent(v)
                failed += 1
            except Exception as exc:  # noqa: BLE001 — one bad row must not
                # stop the sweep from processing the rest, or bubble into
                # the caller's event loop (prod incident: an unguarded
                # exception here starved every other pending intent and
                # was mistaken for the whole backend going down).
                logger.warning("outbox _fail_intent crashed for %s: %s",
                                v.get("id"), exc)
    return {"delivered": delivered, "failed": failed}


def _bump_attempts(intent_id: str, err: str) -> None:
    try:
        with SessionLocal() as db:
            (db.query(DispatchIntent)
               .filter(DispatchIntent.id == intent_id)
               .update({DispatchIntent.attempts: DispatchIntent.attempts + 1,
                        DispatchIntent.last_error: err[:2000]},
                       synchronize_session=False))
            db.commit()
    except Exception:  # noqa: BLE001
        pass


def _fail_intent(v: dict) -> None:
    """TTL exhausted with no daemon: mark failed and surface it the same
    way the old in-memory expiry did."""
    try:
        with SessionLocal() as db:
            (db.query(DispatchIntent)
               .filter(DispatchIntent.id == v["id"],
                       DispatchIntent.status == "pending")
               .update({DispatchIntent.status: "failed",
                        DispatchIntent.last_error: "ttl_expired_no_daemon"},
                       synchronize_session=False))
            db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("outbox fail-mark failed (%s): %s", v["id"], exc)
        return
    logger.warning(
        "outbox TTL expired with no daemon: kind=%s event=%s run=%s task=%s "
        "— marking dropped", v["kind"], v["event_id"], v["run_id"] or "-",
        v["task_id"] or "-")
    if v["kind"] == "trigger" and v["agent_id"]:
        # No agent_id means there's no chat scope to surface this in —
        # writing the SYSTEM message would just be an orphan row (or an
        # FK violation on Postgres). Skip cleanly; the warning above is
        # the record of what happened.
        try:
            from backend.forge import services as _svc
            _svc.mark_dispatch_dropped(
                agent_id=v["agent_id"], trace_id=v["event_id"],
                run_id=v["run_id"] or None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mark_dispatch_dropped failed: %s", exc)


def run_delivery_sweep() -> None:
    """Sync entrypoint for the APScheduler tick — marshals the async
    sweep onto the app's main loop, where the hub's sockets live."""
    from backend.forge.services import _dispatch_coro
    _dispatch_coro(deliver_pending())
