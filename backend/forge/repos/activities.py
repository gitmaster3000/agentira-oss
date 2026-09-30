"""Data access for the Activity ledger (task feed / audit trail)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError

from backend.models import Activity


def task_moves_since(db, *, task_id: str, since: datetime) -> list[Activity]:
    """Status-move rows on a task, newest first, logged at/after `since`."""
    return (db.query(Activity)
              .filter(Activity.task_id == task_id,
                      Activity.action == "task.move",
                      Activity.created_at >= since)
              .order_by(Activity.created_at.desc())
              .all())


def latest_comment_by(db, *, task_id: str, actor: str,
                      since: datetime) -> Activity | None:
    """The actor's most recent comment on a task at/after `since`."""
    return (db.query(Activity)
              .filter(Activity.task_id == task_id,
                      Activity.action == "commented",
                      Activity.actor == actor,
                      Activity.created_at >= since)
              .order_by(Activity.created_at.desc())
              .first())


def count_bounce_escalation_comments(db, *, project_id: str,
                                     since: datetime) -> int:
    """Count of workflow bounce/needs-attention comments on `project_id`'s
    task feed since `since` — the sprint review's systemic-issue signal.
    Both share `action == "commented"`; distinguished by their detail
    marker text (see forge/workflow.py `_bounce_gate_failure`)."""
    from sqlalchemy import or_
    return (db.query(Activity)
              .filter(Activity.project_id == project_id,
                      Activity.actor == "workflow",
                      Activity.action == "commented",
                      Activity.created_at >= since,
                      or_(Activity.detail.ilike("%Bounced back%"),
                          Activity.detail.ilike("%Needs attention%")))
              .count())


def add_task_comment(db, *, project_id: str, task_id: str,
                     detail: str, actor: str = "workflow") -> None:
    """Post a comment on the task feed. Caller owns the commit."""
    db.add(Activity(project_id=project_id, task_id=task_id, actor=actor,
                    action="commented", detail=detail))


def record_review_verdict(db, *, project_id: str, task_id: str, actor: str,
                          verdict: str, note: str = "",
                          run_id: str | None = None) -> bool:
    """Record a reviewer's STRUCTURED verdict (WFE Phase 2).

    The verdict lives in a dedicated `action == "review_verdict"` row with the
    machine-readable value as its own JSON `diff` field — NOT prose in `detail`
    that a gate would string-match. `actor` is the server-injected reviewer
    profile name, so the verdict can't be spoofed by run content. When
    ``run_id`` is supplied, retries are idempotent for that (run, verdict)
    pair. Caller owns the commit. Returns whether a row was added."""
    import json as _json
    payload = {"verdict": verdict}
    idempotency_key = None
    if run_id:
        payload["run_id"] = run_id
        idempotency_key = f"review:{run_id}:{verdict}"
        existing = (db.query(Activity.id)
                      .filter(Activity.idempotency_key == idempotency_key)
                      .first())
        if existing:
            return False

    row = Activity(
        project_id=project_id,
        task_id=task_id,
        actor=actor,
        action="review_verdict",
        detail=(note or f"Review verdict: {verdict}"),
        diff=_json.dumps(payload, sort_keys=True),
        idempotency_key=idempotency_key,
    )
    if idempotency_key is None:
        db.add(row)
        return True

    # The pre-check handles ordinary transport retries. The unique index plus
    # savepoint also closes the race between concurrent retries.
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        return False
    return True


def latest_review_verdict(db, *, task_id: str, actor: str,
                          since: datetime) -> str | None:
    """The actor's most recent structured review verdict on a task at/after
    `since` — the typed value ("approve" / "reject"), or None if none exists."""
    import json as _json
    row = (db.query(Activity)
             .filter(Activity.task_id == task_id,
                     Activity.action == "review_verdict",
                     Activity.actor == actor,
                     Activity.created_at >= since)
             .order_by(Activity.created_at.desc())
             .first())
    if row is None:
        return None
    try:
        return (_json.loads(row.diff or "{}") or {}).get("verdict")
    except (ValueError, TypeError):
        return None
