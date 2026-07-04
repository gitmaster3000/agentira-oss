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


# The reconciler's verdict for a run its daemon stopped reporting. Kept here
# (the Run lifecycle owner) so the resurrection path in
# services.heartbeat_runtimes can recognize — and reverse — exactly this
# verdict when the daemon proves the run alive again. AP-371.
RECONCILED_ERROR = "Run reconciled as failed — daemon stopped reporting it."


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
    from backend.forge.services import _run_to_dict, _notify_project_members
    with SessionLocal() as db:
        agent = db.get(Agent, agent_id)
        agent_name = agent.name if agent else "Agent"
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
        db.flush()
        _notify_project_members(
            db,
            project_id=project_id,
            type_="forge.run.created",
            title=f"{agent_name} run created",
            link=f"/forge/runs/{r.id}",
        )
        db.commit()
        db.refresh(r)
        return _run_to_dict(r)


def get_or_create_task_run(db, *, agent_id: str, task_id: str,
                           project_id: str | None,
                           trigger_event: str = "chat",
                           model_used: str = "",
                           initial_prompt: str = "",
                           worktree_path: str = "",
                           worktree_branch: str = "",
                           log_dir: str = "") -> str:
    """AP-190/AP-335: THE one run per (agent, task), reused across turns.

    Strictly one run per (agent, task): the first dispatch creates the row,
    and EVERY later turn — chat or explicit work — reuses the SAME run,
    resetting it to RUNNING for the new turn (the previous turn's verdict —
    outcome/diff/error — is overwritten at completion). `session_id` (the
    runtime resume handle) and `is_work` are sticky: we keep resuming the same
    conversation, and once a run has done durable work it stays work. Caller
    owns the session and commit; returns the run_id.

    Reuse is NOT scoped by `trigger_event` (AP-335): a chat continues the
    task's single run even if it started as an explicit ``task.scheduled``
    work episode. `trigger_event` is only the label stamped at creation. There
    is never a second run for an (agent, task) — the "don't revive a parked
    run on a comment-wake" safety is enforced upstream by recording the comment
    as context instead of dispatching (see _deliver_comment_to_agent), not by
    opening another run.
    """
    run = (db.query(Run)
             .filter(Run.agent_id == agent_id, Run.task_id == task_id)
             .order_by(Run.created_at.desc())
             .first())
    if run is not None:
        # Reuse: start a fresh turn on the existing episode. Clear the prior
        # turn's terminal verdict + interrupt bookkeeping; completion re-stamps.
        run.status = RunStatus.RUNNING
        run.started_at = _utc_now()
        # AP-371: the reused row carries last_heartbeat_at from its previous
        # life — stale beyond the reconciler threshold, so without a fresh
        # stamp the sweep kills the new turn before the daemon's first report.
        run.last_heartbeat_at = _utc_now()
        run.finished_at = None
        run.duration_ms = None
        run.outcome = None
        run.error = None
        run.interrupt_intent = None
        run.stop_requested_at = None
        if initial_prompt:
            run.initial_prompt = initial_prompt
        if worktree_path:
            run.worktree_path = worktree_path
        if worktree_branch:
            run.worktree_branch = worktree_branch
        if log_dir:
            run.log_dir = log_dir
        if model_used:
            run.model_used = model_used
        db.flush()
        return run.id
    run = Run(
        agent_id=agent_id,
        task_id=task_id,
        project_id=project_id or None,
        trigger_event=trigger_event,
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


def create_chat_run_in_session(db, *, agent_id: str, task_id: str,
                               project_id: str | None,
                               model_used: str,
                               initial_prompt: str,
                               worktree_path: str,
                               worktree_branch: str,
                               log_dir: str) -> str:
    """AP-190: get-or-create THE (agent, task) run for a task-chat turn.

    Thin wrapper over :func:`get_or_create_task_run` — kept for its existing
    call site. Returns the (possibly reused) run_id. `complete_trigger` flips
    is_work=True iff a turn produced durable work; a talk-only turn keeps the
    row is_work=False and the UI shows it as chat.
    """
    return get_or_create_task_run(
        db, agent_id=agent_id, task_id=task_id, project_id=project_id,
        trigger_event="chat", model_used=model_used,
        initial_prompt=initial_prompt, worktree_path=worktree_path,
        worktree_branch=worktree_branch, log_dir=log_dir,
    )


def latest_task_run_is_parked(agent_id: str, task_id: str) -> bool:
    """True if the agent's single run for this task is PAUSED or parked
    (needs_input/blocked).

    A comment-wake must not flip such a run back to RUNNING, and (strictly one
    run per agent+task) must not open a second one — so the caller records the
    comment as context instead of dispatching (see _deliver_comment_to_agent).
    """
    with SessionLocal() as db:
        run = (db.query(Run)
                 .filter(Run.agent_id == agent_id, Run.task_id == task_id)
                 .order_by(Run.created_at.desc())
                 .first())
        if run is None:
            return False
        return (run.status == RunStatus.PAUSED
                or run.outcome in (RunOutcome.NEEDS_INPUT, RunOutcome.BLOCKED))


# ── Run emergence ─────────────────────────────────────────────────────

# CLEANUP(AP-190): delete. No per-turn crystallization — a Run is one-per-task
# (= the chat's work-view), not a row that flips visible when a turn "did work".
def mark_is_work_if_any(run_id: str, *, work_signal: dict | None,
                        has_explicit_outcome: bool) -> bool:
    """Flip a chat run's is_work=True iff the turn produced durable work: a
    working-tree change (per the project's work-signal mode), an agent-declared
    outcome, or a registered artifact. At that point the run surfaces in the
    Runs list; a talk-only turn stays is_work=False and the UI keeps it as
    chat. The row is never deleted — this replaces the old shadow
    delete/promote dance. Only chat runs defer is_work (explicit runs are
    is_work=True at creation). Idempotent. Returns the resulting is_work."""
    from backend.forge import turns as _turns
    with SessionLocal() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r or r.trigger_event != "chat":
            return bool(r and r.is_work)
        if r.is_work:
            return True
        arts = (r.artifacts_json or "").strip()
        had_artifacts = bool(arts) and arts != "[]"
        try:
            mode = _turns.resolve_work_signal_mode(r.project_id)
            did_work = _turns.turn_did_work(work_signal, mode)
        except Exception:  # noqa: BLE001 — never fail completion on a setting read
            did_work = bool((r.diff or "").strip())
        if did_work or has_explicit_outcome or had_artifacts:
            r.is_work = True
            db.commit()
            return True
        return False


# ── Lifecycle transitions ─────────────────────────────────────────────

def start(run_id: str) -> dict | None:
    """PENDING → RUNNING. Marks the agent BUSY."""
    from backend.forge.services import _run_to_dict, _notify_project_members
    with SessionLocal() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return None
        agent = db.get(Agent, r.agent_id) if r.agent_id else None
        agent_name = agent.name if agent else "Agent"
        r.status = RunStatus.RUNNING
        r.started_at = _utc_now()
        # AP-371: a prepared (READY) run can be dispatched minutes after
        # creation, so the reconciler's created_at grace window is long gone.
        # Starting IS a liveness proof — stamp it, giving the daemon a full
        # threshold before the sweep may judge this run.
        r.last_heartbeat_at = _utc_now()
        broadcast_status(run_id, RunStatus.RUNNING)
        if agent:
            agent.status = AgentStatus.BUSY
        _notify_project_members(
            db,
            project_id=r.project_id,
            type_="forge.run.started",
            title=f"{agent_name} run started",
            link=f"/forge/runs/{run_id}",
        )
        db.commit()
        db.refresh(r)
        return _run_to_dict(r)


def complete(run_id: str, *, input_tokens: int = 0,
             output_tokens: int = 0, cost_usd: float = 0.0,
             error: str | None = None) -> dict | None:
    """RUNNING → COMPLETED or FAILED. Updates agent stats; notifies on failure."""
    from backend.forge.services import _run_to_dict, _notify_admins, _notify_project_members
    with SessionLocal() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return None
        agent = db.get(Agent, r.agent_id) if r.agent_id else None
        agent_name = agent.name if agent else "agent"
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
        if agent:
            agent.status = AgentStatus.ONLINE
            agent.total_runs += 1
            agent.total_cost_usd += cost_usd
        if r.status == RunStatus.FAILED:
            short_err = (error or "unknown error")[:140]
            _notify_admins(
                db,
                type_="forge.run.failed",
                title=f"{agent_name} run failed: {short_err}",
                link=f"/forge/runs/{run_id}",
            )
            _notify_project_members(
                db,
                project_id=r.project_id,
                type_="forge.run.failed",
                title=f"{agent_name} run failed",
                link=f"/forge/runs/{run_id}",
            )
        else:
            _notify_project_members(
                db,
                project_id=r.project_id,
                type_="forge.run.completed",
                title=f"{agent_name} run completed",
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
