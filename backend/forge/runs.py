"""Run lifecycle owner — single source of truth for Run row state transitions.

Standard: Run state is mutated via the functions in this module. Existing
direct `Run.status = ...` writes elsewhere are legacy and should migrate
here as those paths are touched.

Stateless module of functions — no shared state, no polymorphism. If you
ever grow Run *variants* with distinct behavior (e.g. dispatch backend A
vs B), promote to a class then.
"""

from __future__ import annotations
from datetime import datetime, timezone

from backend.db import SessionLocal
from backend.forge.models import (
    Agent, Run, AgentStatus, RunStatus, RunOutcome,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── Status broadcast ──────────────────────────────────────────────────

def broadcast_status(run_id: str | None,
                     status: RunStatus | None,
                     outcome: RunOutcome | None = None) -> None:
    """Push a run_status frame to subscribed browsers. Best-effort."""
    if not run_id or status is None:
        return
    try:
        from backend.forge.ws_dispatch import client_hub
        client_hub.broadcast_run_status(
            run_id, status.value,
            outcome.value if outcome is not None else None,
        )
    except Exception:
        pass


# ── Creation ──────────────────────────────────────────────────────────

def create(*, agent_id: str, task_id: str | None = None,
           project_id: str | None = None, trigger_event: str = "",
           model_used: str = "") -> dict:
    """Create a PENDING Run. Used by the Run-button / cron / scheduled paths.

    These are explicitly-started work episodes, so is_work=True — they surface
    in the Runs list immediately (even while still running). Only chat-emergent
    runs defer is_work until completion decides whether work happened."""
    from backend.forge.services import _run_to_dict
    with SessionLocal() as db:
        r = Run(
            agent_id=agent_id,
            task_id=task_id,
            project_id=project_id,
            trigger_event=trigger_event,
            status=RunStatus.PENDING,
            model_used=model_used,
            is_work=True,
        )
        db.add(r)
        db.commit()
        db.refresh(r)
        return _run_to_dict(r)


def create_chat_run_in_session(db, *, agent_id: str, task_id: str,
                               project_id: str | None,
                               model_used: str,
                               initial_prompt: str,
                               worktree_path: str,
                               worktree_branch: str,
                               log_dir: str) -> str:
    """Reserve a Run row for a task-chat turn at dispatch time.

    Caller owns the session and commit. Returns the new run_id.

    Every task-chat turn gets a real run up-front so the agent can register
    artifacts, the daemon can tee logs to a run-keyed dir, and the worktree is
    isolated — BEFORE we know if the turn does work. It starts is_work=False;
    `complete_trigger` sets is_work=True iff the turn produced durable work, at
    which point it surfaces in the Runs list. A talk-only turn stays
    is_work=False and the UI keeps it as chat. (Replaces the old shadow-run
    reservation that was deleted/promoted at completion.)

    Persists `initial_prompt` so post-mortem diagnostics on a stuck run can
    show what the agent was asked to do — without it, a hung run is a blank row.
    """
    run = Run(
        agent_id=agent_id,
        task_id=task_id,
        project_id=project_id or None,
        trigger_event="chat",
        status=RunStatus.RUNNING,
        model_used=model_used,
        initial_prompt=initial_prompt or "",
        worktree_path=worktree_path,
        worktree_branch=worktree_branch,
        log_dir=log_dir,
        started_at=_utc_now(),
        is_work=False,
    )
    db.add(run)
    db.flush()
    return run.id


# ── Lifecycle transitions ─────────────────────────────────────────────

def start(run_id: str) -> dict | None:
    """PENDING → RUNNING. Marks the agent BUSY."""
    from backend.forge.services import _run_to_dict
    with SessionLocal() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return None
        r.status = RunStatus.RUNNING
        r.started_at = _utc_now()
        broadcast_status(run_id, RunStatus.RUNNING)
        if r.agent:
            r.agent.status = AgentStatus.BUSY
        db.commit()
        db.refresh(r)
        return _run_to_dict(r)


def complete(run_id: str, *, input_tokens: int = 0,
             output_tokens: int = 0, cost_usd: float = 0.0,
             error: str | None = None) -> dict | None:
    """RUNNING → COMPLETED or FAILED. Updates agent stats; notifies on failure."""
    from backend.forge.services import _run_to_dict, _notify_admins
    with SessionLocal() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return None
        now = _utc_now()
        r.status = RunStatus.FAILED if error else RunStatus.COMPLETED
        broadcast_status(run_id, r.status)
        r.finished_at = now
        r.input_tokens = input_tokens
        r.output_tokens = output_tokens
        r.cost_usd = cost_usd
        r.error = error
        if r.started_at:
            r.duration_ms = int((now - _utc(r.started_at)).total_seconds() * 1000)
        if r.agent:
            r.agent.status = AgentStatus.ONLINE
            r.agent.total_runs += 1
            r.agent.total_cost_usd += cost_usd
        if r.status == RunStatus.FAILED:
            agent_name = r.agent.name if r.agent else "agent"
            short_err = (error or "unknown error")[:140]
            _notify_admins(
                db,
                type_="forge.run.failed",
                title=f"{agent_name} run failed: {short_err}",
                link=f"/forge/runs/{run_id}",
            )
        db.commit()
        db.refresh(r)
        return _run_to_dict(r)


def cancel(run_id: str) -> dict:
    """Active → INTERRUPTING(discard). Daemon ack flips to CANCELLED.

    Returns immediately so the UI gets feedback without waiting on WS.
    """
    from backend.forge.services import _run_to_dict, _dispatch_coro
    from backend.forge.models import AgentMessage
    from backend.forge.ws_dispatch import hub
    with SessionLocal() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            return {"error": "Run not found"}
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED,
                          RunStatus.CANCELLED, RunStatus.INTERRUPTING):
            return {"error": f"Run already {run.status.value}"}
        agent = db.get(Agent, run.agent_id)
        runtime_id = agent.runtime_id if agent else None
        cancel_scope_key = f"task:{run.task_id}" if run.task_id else ""

        last_msg = (db.query(AgentMessage)
                    .filter(AgentMessage.run_id == run_id)
                    .order_by(AgentMessage.created_at.desc())
                    .first())
        trace_id = last_msg.trace_id if last_msg else ""

        run.status = RunStatus.INTERRUPTING
        run.interrupt_intent = "discard"
        broadcast_status(run_id, RunStatus.INTERRUPTING)
        run.stop_requested_at = _utc_now()
        run.error = "Cancelled by user."
        if run.agent and run.agent.status == AgentStatus.BUSY:
            run.agent.status = AgentStatus.ONLINE
        db.commit()
        db.refresh(run)
        run_dict = _run_to_dict(run)

    if runtime_id:
        try:
            _dispatch_coro(hub.dispatch_cancel(
                runtime_id=runtime_id, trace_id=trace_id, run_id=run_id,
                scope_key=cancel_scope_key,
            ))
        except Exception:
            pass

    return {"ok": True, "run": run_dict}
