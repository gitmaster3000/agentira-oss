"""The "did this turn do work?" decision.

A *turn* is one dispatch (one trace_id). Every task-chat turn gets a real Run
row reserved at dispatch; at completion `complete_trigger` calls `turn_did_work`
to set `Run.is_work` — True surfaces it in the Runs list as a work episode,
False keeps it as plain chat. This module owns only that decision: mapping the
daemon's raw git facts onto the project's work-signal setting. A throwaway "hey"
never becomes a visible Run.

Kept separate from the 4k-line services.py on purpose (it's a cohesive
concern).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("agentira.forge.turns")

# CLEANUP(AP-190): delete this entire module. The "did this turn do work?"
# decision goes away — a Run is the work-view of a task's chat (1 task = 1
# run), not a per-turn crystallization gated on git facts.

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
