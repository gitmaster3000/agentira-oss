"""Workflow driver — interprets the project's configured process flow.

The gate engine (`backend/gates.py`) *validates* transitions; this module
*drives* them: when a run finishes `succeeded`, it looks up the effective
workflow, advances the task to the configured next column (gate-checked),
re-assigns it to the configured role's agent, and dispatches the hand-off run.
This is the missing link that left every task stranded in `in_progress` after
a successful implementer run.

Design rules (locked with the user, 2026-06-10):

- **Config layering.** The FLOW (column order + on_success semantics — the
  secret sauce) is SYSTEM config: `templates/workflow/default.yaml`, shipped
  with the product, not customer-editable. The CUSTOMER surface is small and
  safe: `Project.workflow_enabled` (the opt-in) and
  `Project.workflow_roles_json` (role → agent-matching overrides). A customer
  can re-map who reviews; they cannot rewire the pipeline.
- **Standard parser with safety.** YAML via `yaml.safe_load`, then a Pydantic
  schema (the `backend/template_loader.py` pattern). Malformed customer
  overrides are logged and ignored — the system flow still runs.
- **Prompts/YAML = config; code = checks, integrity, deterministic actions.**
  This module is one of the Conductor's token-free helper scripts (same
  code+LLM split as the queue tick).
- **Policies are config**, e.g. reviewer != implementer is
  `roles.reviewer.exclude_previous_assignee`, not a constant.

Opt-in per project via `Project.workflow_enabled` (OFF by default).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, validator

from backend.db import SessionLocal
from backend.models import Task, Project, Profile, Status
from backend.forge.models import Agent, Run, RunOutcome, RunStatus
from backend import gates

logger = logging.getLogger("agentira.forge.workflow")

_DEFAULT_WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "templates" / "workflow" / "default.yaml"
)


# ── Schema (standard parser + safety: yaml.safe_load → Pydantic) ─────────

class OnSuccess(BaseModel):
    """What the driver does when a run succeeds in a column."""
    advance_to: str
    assign_role: Optional[str] = None
    dispatch: bool = False


class ColumnSpec(BaseModel):
    name: str
    on_success: Optional[OnSuccess] = None

    @validator("name")
    def name_not_empty(cls, v):  # noqa: N805
        if not v.strip():
            raise ValueError("column name cannot be empty")
        return v.strip()


class RoleSpec(BaseModel):
    """How a role resolves to an agent. This is the CUSTOMER-overridable part."""
    match: list[str] = Field(default_factory=list)
    exclude_previous_assignee: bool = False
    fallback: str = "none"          # "any" | "none"

    @validator("fallback")
    def fallback_known(cls, v):  # noqa: N805
        if v not in ("any", "none"):
            raise ValueError("fallback must be 'any' or 'none'")
        return v


class Workflow(BaseModel):
    columns: list[ColumnSpec]
    roles: dict[str, RoleSpec] = Field(default_factory=dict)

    @validator("columns")
    def columns_not_empty(cls, v):  # noqa: N805
        if not v:
            raise ValueError("workflow must define at least one column")
        return v

    def column(self, name: str) -> Optional[ColumnSpec]:
        return next((c for c in self.columns if c.name == name), None)


# ── Loading: system flow + restricted customer override ──────────────────

def system_workflow() -> Workflow:
    """The shipped flow (system config — not customer-editable). Raises loudly
    on a malformed file: that's a packaging bug, not a runtime condition."""
    raw = _DEFAULT_WORKFLOW_PATH.read_text(encoding="utf-8")
    return Workflow(**yaml.safe_load(raw))


def effective_workflow(project) -> Workflow:
    """System flow + the project's role overrides (the only customer knob).

    `Project.workflow_roles_json` may re-map how roles resolve to agents
    (match strings, exclusion, fallback). It cannot add/remove/reorder columns
    or change on_success semantics — that surface stays system-owned. A
    malformed override is logged and ignored; the system flow still runs.
    """
    flow = system_workflow()
    raw = getattr(project, "workflow_roles_json", None)
    if not raw:
        return flow
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("roles override must be a JSON object")
        overridden = dict(flow.roles)
        for name, spec in data.items():
            overridden[name] = RoleSpec(**spec)   # validated, not dict-poked
        flow.roles = overridden
    except Exception as exc:  # noqa: BLE001 — bad override never kills the loop
        logger.warning("project %s workflow_roles_json invalid (%s) — "
                       "using system roles", getattr(project, "id", "?"), exc)
    return flow


# ── Helpers (code = deterministic actions + integrity) ───────────────────

def _status_name(db, status_id: str) -> str | None:
    row = db.get(Status, status_id) if status_id else None
    return row.name if row else None


def _already_handed_off(db, run: Run, task: Task) -> bool:
    """Idempotency guard: if any run on this task was created after this one,
    the hand-off already happened (or a human re-dispatched) — skip."""
    newer = (db.query(Run)
               .filter(Run.task_id == task.id, Run.created_at > run.created_at)
               .first())
    return newer is not None


def _in_flight(db, agent_id: str) -> int:
    return (db.query(Run)
              .filter(Run.agent_id == agent_id,
                      Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING,
                                      RunStatus.PAUSED]))
              .count())


def pick_role_agent(db, *, project_id: str, role: RoleSpec,
                    previous_agent_id: str | None) -> Agent | None:
    """Resolve a role to a live agent.

    Candidates: conductor-enabled agents bound to the project with a runtime.
    `exclude_previous_assignee` removes the agent whose run just finished
    (reviewer != implementer when set). Name `match` substrings pick
    specialists; fallback `any` takes the least-loaded candidate, `none`
    returns None (don't advance — safer for review)."""
    profiles = (db.query(Profile)
                  .filter(Profile.conductor_enabled == True)  # noqa: E712
                  .filter(Profile.default_project_id == project_id)
                  .all())
    candidates: list[Agent] = []
    for prof in profiles:
        agent = db.query(Agent).filter(Agent.profile_id == prof.id).first()
        if not agent or not agent.runtime_id:
            continue
        if (role.exclude_previous_assignee and previous_agent_id
                and agent.id == previous_agent_id):
            continue
        candidates.append(agent)
    if not candidates:
        return None
    matches = [m.lower() for m in role.match]
    named = [a for a in candidates
             if any(m in (a.name or "").lower() for m in matches)]
    if named:
        return named[0]
    if role.fallback == "any":
        return min(candidates, key=lambda a: _in_flight(db, a.id))
    return None


# ── The driver ────────────────────────────────────────────────────────────

def advance_after_run(run_id: str) -> dict:
    """Drive the board one configured step after a successful run.

    Safe to call on every finish_run — no-ops unless the project opted in,
    the run succeeded, and the flow defines `on_success` for the task's
    current column. Never raises into the caller."""
    try:
        with SessionLocal() as db:
            run = db.query(Run).filter(Run.id == run_id).first()
            if not run or run.outcome != RunOutcome.SUCCEEDED or not run.task_id:
                return {"advanced": False, "reason": "not_a_successful_task_run"}
            task = db.get(Task, run.task_id)
            if not task:
                return {"advanced": False, "reason": "task_gone"}
            project = db.get(Project, task.project_id) if task.project_id else None
            if not project or not getattr(project, "workflow_enabled", False):
                return {"advanced": False, "reason": "workflow_disabled"}
            if _already_handed_off(db, run, task):
                return {"advanced": False, "reason": "already_handed_off"}

            flow = effective_workflow(project)
            current = _status_name(db, task.status_id)
            col = flow.column(current) if current else None
            spec = col.on_success if col else None
            if not spec:
                return {"advanced": False, "reason": f"no_on_success_for_{current}"}
            target = spec.advance_to

            # The driver respects the same evidence a manual move would.
            fails = gates.failures(
                gates.evaluate(task, from_status=current, to_status=target))
            if fails:
                logger.info("workflow: %s gate blocks %s->%s: %s",
                            task.key or task.id, current, target,
                            [f.name for f in fails])
                return {"advanced": False, "reason": "gate_failed",
                        "failures": [f.name for f in fails]}

            target_status = db.query(Status).filter(Status.name == target).first()
            if not target_status:
                return {"advanced": False, "reason": f"unknown_column_{target}"}

            next_agent = None
            if spec.assign_role:
                role = flow.roles.get(spec.assign_role)
                if role is None:
                    return {"advanced": False, "reason": "role_undefined",
                            "role": spec.assign_role}
                next_agent = pick_role_agent(
                    db, project_id=task.project_id, role=role,
                    previous_agent_id=run.agent_id)
                if next_agent is None:
                    logger.info("workflow: no agent for role=%s on %s — "
                                "not advancing", spec.assign_role,
                                task.key or task.id)
                    return {"advanced": False, "reason": "no_role_agent",
                            "role": spec.assign_role}

            task.status_id = target_status.id
            if next_agent:
                task.assignee = next_agent.name
            db.commit()
            task_id, task_key = task.id, (task.key or task.id)
            next_agent_id = next_agent.id if next_agent else None
            next_agent_name = next_agent.name if next_agent else None

        result: dict = {"advanced": True, "to": target,
                        "assignee": next_agent_name}
        if spec.dispatch and next_agent_id:
            # Dispatch outside the session (schedule_task_run owns its own).
            # The Conductor tick only dispatches `todo` and skips tasks that
            # already have a run — hand-offs dispatch here.
            from backend.forge import services
            d = services.schedule_task_run(task_id=task_id,
                                           agent_id=next_agent_id)
            if isinstance(d, dict) and d.get("error"):
                logger.warning("workflow: hand-off dispatch failed %s -> %s: %s",
                               task_key, next_agent_name, d["error"])
                result["dispatch_error"] = d["error"]
            else:
                result["run_id"] = d.get("run_id") if isinstance(d, dict) else None
        logger.info("workflow: %s %s->%s assignee=%s run=%s",
                    task_key, current, target, next_agent_name,
                    result.get("run_id"))
        return result
    except Exception as exc:  # noqa: BLE001 — never break finish_run
        logger.exception("workflow.advance_after_run failed for %s: %s",
                         run_id, exc)
        return {"advanced": False, "reason": "exception", "error": str(exc)}
