"""AP-158: column-exit gates on task transitions.

A gate is a small check that runs against a task row at the moment its
status would change. Failed gates block the move with structured
reasons ("you said review → done but the PR isn't linked yet").

Which checks guard which transition is workflow CONFIG, not code: the
`checks:` map in `templates/workflow/default.yaml` (`"from->to": [kind, ...]`,
read through `backend.forge.workflow.effective_workflow`). This module is
the registry of check kinds those lists can name:

  has_dod, has_assignee, dod_all_checked, has_branch_or_pr, pr_url_set, proof

Phase 1 kinds are **local** — each reads fields already on the Task row (its
attachments and linked commits included). No GitHub API calls, no webhooks.

Phase 2 (separate ticket) wires the remote-state gates: `pr_merged`,
`ci_passing(required=[…])`, `reviewer_approved`. Those need GitHub
API integration which intersects with the CI/CD wiring (AP-159).

Per-project opt-in: `Project.gates_enabled`. False/NULL = today's
behavior (move_task is RBAC-only). True = the engine evaluates each
transition.

Convention: functions, not classes. Each check is a small pure-ish
function taking `(task)` and returning a `GateResult`.
"""

from __future__ import annotations

import json as _json
import logging
from dataclasses import dataclass
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


# Attachment kinds that count as proof of manual, end-to-end testing.
_PROOF_KINDS = frozenset({"test-report", "recording", "screenshot"})
_PROOF_MISSING = ("Test it yourself end to end and attach the proof "
                  "(test report or screenshot).")
_PROOF_STALE = ("Your proof is older than your last change. Test it again "
                "after your last change and attach fresh proof "
                "(test report or screenshot).")


def _latest_commit_at(task: Task):
    """When the task's newest linked commit was made (None = none linked)."""
    stamps = [(c.committed_at or c.created_at) for c in task.commits
              if (c.kind or "commit") == "commit"]
    stamps = [t for t in stamps if t is not None]
    return max(stamps) if stamps else None


def proof_attachments(task: Task) -> list:
    """The task's proof attachments (test report / recording / screenshot)
    added after its latest commit, newest first."""
    latest = _latest_commit_at(task)
    proofs = [a for a in task.attachments
              if (a.kind or "other") in _PROOF_KINDS
              and (latest is None or a.created_at is None
                   or a.created_at > latest)]
    return sorted(proofs, key=lambda a: a.created_at, reverse=True)


def proof_summary(task: Task) -> dict:
    """What the task page shows: who tested it and which proof to open.
    `stale` = proof exists but predates the latest commit."""
    proofs = proof_attachments(task)
    if proofs:
        a = proofs[0]
        return {"present": True, "tested_by": a.uploaded_by,
                "attachment_id": a.id, "filename": a.filename,
                "kind": a.kind, "at": a.created_at.isoformat()}
    stale = any((a.kind or "other") in _PROOF_KINDS for a in task.attachments)
    return {"present": False, "stale": stale}


def _proof(task: Task) -> GateResult:
    if proof_attachments(task):
        return GateResult("proof", True)
    any_proof = any((a.kind or "other") in _PROOF_KINDS
                    for a in task.attachments)
    return GateResult("proof", False,
                      _PROOF_STALE if any_proof else _PROOF_MISSING)


# ── Registry of check kinds ─────────────────────────────────────────────

# The kinds a workflow's `checks:` list may name. Which transition runs which
# kinds lives in templates/workflow/default.yaml — not here.
CHECKS: dict[str, Callable[[Task], GateResult]] = {
    "has_dod": _has_dod,
    "has_assignee": _has_assignee,
    "dod_all_checked": _dod_all_checked,
    "has_branch_or_pr": _has_branch_or_pr,
    "pr_url_set": _pr_url_set,
    "proof": _proof,
}


def checks_for(project, from_status: str, to_status: str) -> list[str]:
    """The check kinds the effective workflow declares for a transition.
    Empty = no checks (always allowed). Reverse moves are never listed:
    un-shipping is always allowed."""
    from backend.forge.workflow import effective_workflow
    return list(effective_workflow(project).checks.get(
        f"{from_status}->{to_status}", []))


# ── Engine ─────────────────────────────────────────────────────────────

def evaluate(task: Task, *, from_status: str, to_status: str) -> list[GateResult]:
    """Run every check the workflow declares for (from_status → to_status).

    Returns the full list, ok and failed alike, so callers can show a
    "2 of 3 passed" UI if they want. Empty list = no checks declared
    for this transition (always allowed).
    """
    kinds = checks_for(task.project, from_status, to_status)
    return [CHECKS[k](task) for k in kinds]


def failures(results: Iterable[GateResult]) -> list[GateResult]:
    """Convenience: just the failing ones."""
    return [r for r in results if not r.ok]


# Static, task-independent descriptions of each gate — the read-only workflow
# UI (the runtime `reason` on GateResult is task-specific; this is the rule
# itself). Keyed by the gate's name.
_GATE_META: dict[str, str] = {
    "has_dod": "Task has at least one Definition-of-Done item.",
    "has_assignee": "Task has an assignee.",
    "dod_all_checked": "Every Definition-of-Done item is checked.",
    "has_branch_or_pr": "Task has a branch or a PR URL.",
    "pr_url_set": "Task has a PR URL linked.",
    "proof": "Tested end to end by the agent — a test report, recording or "
             "screenshot attached after the last change.",
}


def describe_transition(from_status: str, to_status: str, *,
                        project=None) -> list[dict]:
    """Static description of the checks guarding a transition — for the
    read-only workflow UI. Each entry: {name, description}. Empty list when
    the workflow declares no checks for it (always allowed)."""
    return [{"name": k, "description": _GATE_META.get(k, k)}
            for k in checks_for(project, from_status, to_status)]


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
