"""Data access for the AP-404 Phase 0 audit trail: transition_events and
gate_evaluations. Every task status change and every gates.py evaluation
writes through here — see plan v4 §4 ("one evaluation path — storage")."""

from __future__ import annotations

import json

from backend.forge.models import GateEvaluation, TransitionEvent


def record_transition(db, *, task_id: str, from_status: str | None,
                      to_status: str | None, actor_type: str, actor_id: str,
                      cause: str, result: str) -> TransitionEvent:
    """Append a transition_events row. Caller owns the commit."""
    ev = TransitionEvent(
        task_id=task_id, from_status=from_status, to_status=to_status,
        actor_type=actor_type, actor_id=actor_id or "", cause=cause,
        result=result,
    )
    db.add(ev)
    db.flush()
    return ev


def record_gate_evaluation(db, *, task_id: str, from_status: str | None,
                           to_status: str | None, gate_id: str,
                           evidence_snapshot: dict, outcome: str,
                           reason: str, duration_ms: int,
                           rule_version: str | None = None) -> GateEvaluation:
    """Append a gate_evaluations row. Caller owns the commit."""
    row = GateEvaluation(
        task_id=task_id, transition=f"{from_status}:{to_status}",
        gate_id=gate_id, rule_version=rule_version,
        evidence_snapshot=json.dumps(evidence_snapshot), outcome=outcome,
        reason=reason, duration_ms=duration_ms,
    )
    db.add(row)
    db.flush()
    return row


def has_driver_event_for_run(db, *, task_id: str, run_id: str) -> bool:
    """AP-402: explicit hand-off check. True iff the workflow driver already
    wrote a transition_events row for THIS run (cause == "run:<run_id>") —
    idempotency by recorded fact, not by comparing Run.created_at timestamps
    (the timestamp inference could race and deadlock the pipeline)."""
    return (db.query(TransitionEvent)
              .filter(TransitionEvent.task_id == task_id,
                      TransitionEvent.actor_type == "workflow",
                      TransitionEvent.cause == f"run:{run_id}")
              .first()) is not None
