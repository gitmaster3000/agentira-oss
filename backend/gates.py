"""AP-158: column-exit gates on task transitions.

A gate is a small check that runs against a task row at the moment its
status would change. Failed gates block the move with structured
reasons ("you said review → done but the PR isn't linked yet").

Phase 1 (this module) — **local gates only**. Every checker reads
fields already on the Task row (or the Run row for run-existence).
No GitHub API calls, no webhooks. The point is to make obvious
shortcuts impossible:

  backlog → todo         needs `has_dod`, `has_assignee`
  todo → in_progress     needs `has_assignee`
  in_progress → review   needs `dod_all_checked` + `has_branch_or_pr`
  review → done          needs `pr_url_set` + `dod_all_checked`

Phase 2 (separate ticket) wires the remote-state gates: `pr_merged`,
`ci_passing(required=[…])`, `reviewer_approved`. Those need GitHub
API integration which intersects with the CI/CD wiring (AP-159).

Per-project opt-in: `Project.gates_enabled`. False/NULL = today's
behavior (move_task is RBAC-only). True = the engine evaluates each
transition.

Convention: functions, not classes. Each gate is a small pure-ish
function taking `(task)` and returning `(ok, reason)`.
"""

from __future__ import annotations

import json as _json
import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable

from backend.models import Task


logger = logging.getLogger("agentira.gates")


# ── Result type ─────────────────────────────────────────────────────────

@dataclass
class GateResult:
    """One gate's verdict."""
    name: str
    ok: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "reason": self.reason}


# ── Individual gate checkers ────────────────────────────────────────────

def _has_dod(task: Task) -> GateResult:
    raw = task.dod_items or ""
    if not raw.strip():
        return GateResult("has_dod", False,
                          "Task needs at least one DoD item before leaving backlog.")
    try:
        items = _json.loads(raw)
    except Exception:  # noqa: BLE001
        return GateResult("has_dod", False, "DoD JSON is malformed.")
    if not isinstance(items, list) or not items:
        return GateResult("has_dod", False, "DoD list is empty.")
    return GateResult("has_dod", True)


def _has_assignee(task: Task) -> GateResult:
    if not (task.assignee or "").strip():
        return GateResult("has_assignee", False,
                          "Task needs an assignee.")
    return GateResult("has_assignee", True)


def _dod_all_checked(task: Task) -> GateResult:
    raw = task.dod_items or ""
    if not raw.strip():
        return GateResult("dod_all_checked", False,
                          "No DoD items defined — can't certify completion.")
    try:
        items = _json.loads(raw)
    except Exception:  # noqa: BLE001
        return GateResult("dod_all_checked", False, "DoD JSON is malformed.")
    if not isinstance(items, list) or not items:
        return GateResult("dod_all_checked", False, "DoD list is empty.")
    unchecked = [i for i in items if not i.get("checked")]
    if unchecked:
        labels = [str(i.get("text", "?"))[:40] for i in unchecked[:3]]
        more = f" (+{len(unchecked) - 3} more)" if len(unchecked) > 3 else ""
        return GateResult("dod_all_checked", False,
                          f"DoD items still open: {labels}{more}")
    return GateResult("dod_all_checked", True)


def _has_branch_or_pr(task: Task) -> GateResult:
    if (task.branch or "").strip() or (task.pr_url or "").strip():
        return GateResult("has_branch_or_pr", True)
    return GateResult("has_branch_or_pr", False,
                      "Set a branch (or PR URL) before sending to review.")


def _pr_url_set(task: Task) -> GateResult:
    if (task.pr_url or "").strip():
        return GateResult("pr_url_set", True)
    return GateResult("pr_url_set", False,
                      "Link the PR URL before marking done.")


# ── Per-transition gate map ─────────────────────────────────────────────

# Key: (from_status, to_status). Value: list of gate functions to run.
# Reverse transitions (review → in_progress, etc.) intentionally have no
# gates — un-shipping is always allowed.
_TRANSITION_GATES: dict[tuple[str, str], list[Callable[[Task], GateResult]]] = {
    ("backlog", "todo"):        [_has_dod, _has_assignee],
    ("todo", "in_progress"):    [_has_assignee],
    ("in_progress", "review"):  [_dod_all_checked, _has_branch_or_pr],
    ("review", "done"):         [_pr_url_set, _dod_all_checked],
}


# ── Engine ─────────────────────────────────────────────────────────────

def evaluate(task: Task, *, from_status: str, to_status: str) -> list[GateResult]:
    """Run every gate registered for (from_status → to_status).

    Returns the full list, ok and failed alike, so callers can show a
    "2 of 3 passed" UI if they want. Empty list = no gates registered
    for this transition (always allowed).
    """
    fns = _TRANSITION_GATES.get((from_status, to_status), [])
    return [fn(task) for fn in fns]


def failures(results: Iterable[GateResult]) -> list[GateResult]:
    """Convenience: just the failing ones."""
    return [r for r in results if not r.ok]


def enforce(task: Task, *, from_status: str, to_status: str) -> None:
    """Raise `GateFailure` if any gate fails. No-op on success.

    Callers wrap this in their transition path; REST translates the
    exception into a 422 with the structured failures.
    """
    failed = failures(evaluate(task, from_status=from_status,
                                to_status=to_status))
    if failed:
        logger.info("gate refusal task=%s %s→%s — %s",
                    task.id, from_status, to_status,
                    ", ".join(f.name for f in failed))
        raise GateFailure(from_status, to_status, failed)


class GateFailure(Exception):
    """One or more gates blocked a task transition."""

    def __init__(self, from_status: str, to_status: str,
                 failed_gates: list[GateResult]):
        self.from_status = from_status
        self.to_status = to_status
        self.failed_gates = failed_gates
        names = ", ".join(g.name for g in failed_gates)
        super().__init__(
            f"Transition {from_status} → {to_status} blocked by: {names}"
        )

    def to_dict(self) -> dict:
        return {
            "error": "transition_blocked",
            "from_status": self.from_status,
            "to_status": self.to_status,
            "failed_gates": [g.to_dict() for g in self.failed_gates],
        }
