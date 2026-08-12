"""Canonical run state machine — the executable form of docs-oss/docs/technical/run-state-machine.md.

Single source of truth for *which transitions are legal*. Both the backend
lifecycle (runs.py) and tests assert against `can_transition`. If you change the
state machine, change docs-oss/docs/technical/run-state-machine.md first, then this map, then the
frontend STATUS_CONFIG.

Stateless: a transition map + two helpers. No shared state.
"""

from __future__ import annotations

from backend.forge.models import RunStatus

# Terminal states have no outgoing transitions. PAUSED is *resumable-terminal*:
# no process runs, but Resume moves it back to PENDING — so it is NOT terminal.
TERMINAL: frozenset[RunStatus] = frozenset({
    RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED,
})

# "Is the agent working right now?" — drives the single liveness signal.
LIVE: frozenset[RunStatus] = frozenset({
    RunStatus.PENDING, RunStatus.RUNNING, RunStatus.INTERRUPTING,
})

# Every legal transition. from-status -> set(allowed to-status).
# Mirrors the transition table in docs-oss/docs/technical/run-state-machine.md exactly.
_ALLOWED: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.READY: frozenset({RunStatus.PENDING, RunStatus.CANCELLED}),
    RunStatus.PENDING: frozenset({
        RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED,
    }),
    RunStatus.RUNNING: frozenset({
        RunStatus.INTERRUPTING, RunStatus.COMPLETED, RunStatus.FAILED,
    }),
    RunStatus.INTERRUPTING: frozenset({
        RunStatus.PAUSED, RunStatus.CANCELLED,
    }),
    RunStatus.PAUSED: frozenset({
        RunStatus.PENDING, RunStatus.CANCELLED,
    }),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def can_transition(frm: RunStatus, to: RunStatus) -> bool:
    """True iff frm -> to is a legal transition (or a no-op re-write)."""
    if frm == to:
        return True
    return to in _ALLOWED.get(frm, frozenset())


def is_terminal(status: RunStatus) -> bool:
    return status in TERMINAL


def is_live(status: RunStatus) -> bool:
    """The run is actively in flight (pending/running/interrupting)."""
    return status in LIVE
