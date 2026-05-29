"""The turn -> run model (ADR 009 / AP-136).

A *turn* is one dispatch (one trace_id). A *run* is an emergent span over the
turns that did work. This module owns two things:

  - the "did this turn do work?" decision, mapping the daemon's raw git facts
    onto the project's work-signal setting, and
  - lazy creation of a Run for a standalone (chat) turn that produced work,

so runs stay meaningful work episodes without the user having to declare one,
and a throwaway "hey" never becomes a run.

Kept separate from the 4k-line services.py on purpose (it's a cohesive new
concern). It lazy-imports from services to avoid an import cycle.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("agentira.forge.turns")

WORK_SIGNAL_MODES = ("working_tree", "tracked", "committed")
DEFAULT_WORK_SIGNAL = "working_tree"


def resolve_work_signal_mode(project_id: str | None) -> str:
    """The project's work-signal setting; defaults to the robust
    ``working_tree`` (nothing the agent touches is lost). The per-project
    override column + UI land with EPIC E3 / AP-131; until then this is the
    workspace default and tolerates the column not existing yet."""
    if not project_id:
        return DEFAULT_WORK_SIGNAL
    try:
        from backend.forge.services import _session
        from backend.models import Project
        with _session() as db:
            p = db.get(Project, project_id)
            mode = getattr(p, "work_signal", None) if p else None
        if mode in WORK_SIGNAL_MODES:
            return mode
    except Exception:  # noqa: BLE001 — never fail completion on a setting read
        pass
    return DEFAULT_WORK_SIGNAL


def turn_did_work(work_signal: dict | None, mode: str) -> bool:
    """Map the daemon's raw git facts {tracked, untracked, committed} onto
    the work-signal mode. (register_run_artifact / finish_run are handled by
    the caller — a standalone chat turn has no run to attach those to, so for
    crystallization the git signal is what counts.)"""
    ws = work_signal or {}
    if mode == "committed":
        return bool(ws.get("committed"))
    if mode == "tracked":
        return bool(ws.get("tracked"))
    # working_tree (default): any tracked change OR a new untracked file.
    return bool(ws.get("tracked") or ws.get("untracked"))


def maybe_crystallize_chat_turn(
    *, agent_id: str, trace_id: str, scope_key: str,
    work_signal: dict | None, diff_stat: str = "", diff: str = "",
    input_tokens: int = 0, output_tokens: int = 0,
) -> str | None:
    """If a standalone (run-less) task chat turn produced work, create a Run
    spanning it and backfill run_id onto the turn's messages so the thread
    groups under the run and the work is traceable. Returns the new run_id,
    or None when the turn was just talk (or not a task scope).

    Only fires for ``task:`` scopes — that's where a run belongs; a free-form
    project/default chat that happens to touch files is left as a turn.
    """
    if not scope_key or not scope_key.startswith("task:"):
        return None
    task_id = scope_key.split(":", 1)[1]

    from datetime import datetime, timezone
    from backend.forge.services import (
        _session, create_run, _compute_worktree_paths,
    )
    from backend.forge.models import Run, RunStatus, RunOutcome, AgentMessage
    from backend.models import Task

    with _session() as db:
        task = db.get(Task, task_id)
        if not task:
            return None
        project_id = task.project_id

    if not turn_did_work(work_signal, resolve_work_signal_mode(project_id)):
        return None

    run = create_run(agent_id=agent_id, task_id=task_id, project_id=project_id,
                     trigger_event="chat.work", model_used="")
    run_id = run["id"]
    wt_path, wt_branch = _compute_worktree_paths(
        agent_id=agent_id, project_id=project_id, task_id=task_id)
    now = datetime.now(timezone.utc)
    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if r:
            r.status = RunStatus.COMPLETED
            r.outcome = RunOutcome.SUCCEEDED
            r.finished_at = now
            r.diff_stat = diff_stat or ""
            r.diff = diff or ""
            r.input_tokens = input_tokens or 0
            r.output_tokens = output_tokens or 0
            r.worktree_path = wt_path
            r.worktree_branch = wt_branch
            r.summary = "Emergent run — a chat turn produced changes."
        # Group this turn's messages under the new run.
        db.query(AgentMessage).filter(
            AgentMessage.trace_id == trace_id,
            AgentMessage.run_id.is_(None),
        ).update({"run_id": run_id}, synchronize_session=False)
        db.commit()
    logger.info("crystallized chat turn into run=%s scope=%s", run_id, scope_key)
    return run_id
