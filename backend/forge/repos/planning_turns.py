"""Data access for the Conductor's PlanningTurn audit log (AP-401)."""

from __future__ import annotations

import json

from backend.forge.models import PlanningTurn


def create_planning_turn(
    db, *, trigger: str = "cron", status: str = "dispatched",
    model: str | None = None, token_cost: float | None = None,
    duration_ms: int | None = None, facts_snapshot: dict | None = None,
    decisions: list[dict] | None = None,
    conversation_scope_key: str | None = None,
) -> PlanningTurn:
    """Persist one planning-turn record. Caller owns the commit."""
    row = PlanningTurn(
        trigger=trigger, status=status, model=model,
        token_cost=token_cost, duration_ms=duration_ms,
        facts_snapshot_json=json.dumps(facts_snapshot or {}),
        decisions_json=json.dumps(decisions or []),
        conversation_scope_key=conversation_scope_key,
    )
    db.add(row)
    db.flush()
    return row


def append_decision(db, turn_id: str, decision: dict) -> PlanningTurn | None:
    """Append one decision {action, task_id, agent, reason} to a turn's
    decisions list. Caller owns the commit."""
    row = db.get(PlanningTurn, turn_id)
    if row is None:
        return None
    decisions = json.loads(row.decisions_json or "[]")
    decisions.append(decision)
    row.decisions_json = json.dumps(decisions)
    db.flush()
    return row


def set_scope_key(db, turn_id: str, scope_key: str) -> PlanningTurn | None:
    """Attach the turn's conversation scope key once the dispatch has a
    turn_id to build `turn:{turn_id}` from. Caller owns the commit."""
    row = db.get(PlanningTurn, turn_id)
    if row is None:
        return None
    row.conversation_scope_key = scope_key
    db.flush()
    return row


def update_status(db, turn_id: str, status: str) -> PlanningTurn | None:
    """Flip a turn's status (e.g. dispatched -> error) after a send
    failure. Caller owns the commit."""
    row = db.get(PlanningTurn, turn_id)
    if row is None:
        return None
    row.status = status
    db.flush()
    return row


def to_dict(row: PlanningTurn) -> dict:
    return {
        "id": row.id,
        "trigger": row.trigger,
        "status": row.status,
        "model": row.model,
        "token_cost": row.token_cost,
        "duration_ms": row.duration_ms,
        "facts_snapshot": json.loads(row.facts_snapshot_json or "{}"),
        "decisions": json.loads(row.decisions_json or "[]"),
        "conversation_scope_key": row.conversation_scope_key,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_recent(db, *, limit: int = 20) -> list[dict]:
    """Most recent planning turns, newest first, for the Conductor feed."""
    rows = (db.query(PlanningTurn)
              .order_by(PlanningTurn.created_at.desc())
              .limit(limit)
              .all())
    return [to_dict(r) for r in rows]
