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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, model_validator, validator

from backend.db import SessionLocal
from backend.models import Task, Project, Profile, Status
from backend.forge.models import Agent, Run, RunOutcome, RunStatus
from backend.forge.repos import runs as runs_repo
from backend.forge.repos import transitions as transitions_repo
from backend import gates

logger = logging.getLogger("agentira.forge.workflow")

_DEFAULT_WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "templates" / "workflow" / "default.yaml"
)
# Per-role hand-off prompts (config): templates/workflow/prompts/<role>.md is
# prepended as hand-off instructions when the driver dispatches that role —
# the reviewer gets a review job description, not the implementer contract.
_PROMPTS_DIR = _DEFAULT_WORKFLOW_PATH.parent / "prompts"

def _load_prompt_file(name: str) -> str:
    """A workflow prompt template (config), or '' if absent. Used for the
    AP-231 gate-bounce corrective message — a one-off signal on the existing
    extra_context channel, NOT a standing context layer."""
    try:
        return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def _prompt_overrides(project) -> dict[str, str]:
    """Per-project prompt-text overrides. `{}` on empty/missing/malformed —
    system templates always remain the ground truth (they are shipped code)."""
    if project is None:
        return {}
    raw = getattr(project, "workflow_prompts_json", None)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items()
                if isinstance(k, str) and isinstance(v, str) and v.strip()}
    except (ValueError, TypeError):
        logger.warning("project %s workflow_prompts_json invalid — using "
                       "system templates", getattr(project, "id", "?"))
        return {}


def _resolve_prompt(project, name: str) -> str:
    """Effective text for a workflow prompt slug: project override > system
    template file > ''. Same slug space as `_load_prompt_file`."""
    return _prompt_overrides(project).get(name) or _load_prompt_file(name)


def _role_handoff_prompt(flow: "Workflow", role_name: str, *,
                         project=None, overrides: dict | None = None,
                         branch: str = "", pr_url: str = "") -> str:
    """The hand-off instructions for a dispatched role (reviewer,
    documentation, ...) — column semantics must not depend on agent persona.

    Resolution order: the role's `prompt` override (customer config, via
    `Project.workflow_roles_json`) -> a system template file named after the
    role -> '' (missing file is legal — roles are user-definable). Loaded
    file is returned with {{BRANCH}} / {{PR_URL}} substituted, same mechanism
    as gate_bounce's {{FAILURES}}."""
    role = flow.roles.get(role_name)
    prompt_name = (role.prompt if role and role.prompt else role_name)
    if overrides is not None:
        content = overrides.get(prompt_name) or _load_prompt_file(prompt_name)
    else:
        content = _resolve_prompt(project, prompt_name)
    if not content:
        logger.info("workflow: no hand-off prompt file for role=%s "
                    "(prompt=%s) — dispatching without it", role_name,
                    prompt_name)
        return ""
    return content.replace("{{BRANCH}}", branch or "(no branch set)") \
                  .replace("{{PR_URL}}", pr_url or "(no PR URL set)")


def resolve_role_prompt(flow: "Workflow", role_name: str, *, project=None) -> str:
    """The hand-off prompt template for a role (config, customer-readable) —
    same resolution as `_role_handoff_prompt` but WITHOUT the per-run
    branch/PR substitution, for the read-only workflow UI. '' if none."""
    role = flow.roles.get(role_name)
    prompt_name = (role.prompt if role and role.prompt else role_name)
    return _resolve_prompt(project, prompt_name)


def role_prompt_slug(flow: "Workflow", role_name: str) -> str:
    """The prompt-file basename a role resolves to — the key the override
    JSON uses. Falls back to the role name."""
    role = flow.roles.get(role_name)
    return (role.prompt if role and role.prompt else role_name)


def column_ui_details(flow: "Workflow", project=None) -> dict:
    """Per-column enrichment for the read-only workflow UI.

    For each column:
      advance_to:  the column a successful task moves to (or None — terminal).
      gates:       the checks a task must pass to LEAVE this column, each
                   {name, description}, sourced from backend.gates (the same
                   engine that actually blocks the move) — never a UI copy.
      prompt_role / prompt: the hand-off template an agent receives when a task
                   ENTERS this column — resolved from the previous column's
                   on_success.assign_role, or this column's on_enter.dispatch_
                   role (e.g. review←reviewer, done←documentation).
    """
    from backend import gates
    # The role dispatched INTO each column (keyed by the target column name).
    incoming: dict[str, str] = {}
    for col in flow.columns:
        s = col.on_success
        if s and s.advance_to and s.assign_role:
            incoming[s.advance_to] = s.assign_role
    details: dict[str, dict] = {}
    for col in flow.columns:
        s = col.on_success
        to = s.advance_to if s else None
        role = incoming.get(col.name) or (
            col.on_enter.dispatch_role if col.on_enter else None)
        prompt_slug = role_prompt_slug(flow, role) if role else ""
        details[col.name] = {
            "advance_to": to,
            "gates": gates.describe_transition(col.name, to) if to else [],
            "prompt_role": role,
            "prompt_slug": prompt_slug,
            "prompt": resolve_role_prompt(flow, role, project=project) if role else "",
            "prompt_is_override": bool(prompt_slug and prompt_slug in _prompt_overrides(project)),
        }
    return details


# ── Schema (standard parser + safety: yaml.safe_load → Pydantic) ─────────

class VerifySpec(BaseModel):
    """Loop v1 C6 — merged-tree verification POLICY. The command itself is
    per-project (`Project.verify_cmd`); this says whether a merge may happen
    without one, and the fallback time limit."""
    required: bool = True             # no verify_cmd → merge refused
    default_timeout_minutes: int = 30  # when the project sets none


class IntegrationFailureSpec(BaseModel):
    """Loop v1 C6 — what happens when the daemon's merge (+ checks) fails.
    Failure kinds are the daemon's classified reason prefixes
    (daemon/integrate.py). Listed kinds go back to whoever owes the fix;
    anything else (push rejected, clone unavailable…) is infrastructure: the
    task stays put and humans are notified. Shares the bounce budget."""
    hand_back_on: list[str] = Field(default_factory=list)
    to_column: str = ""               # must name a column (validated)
    assign: str = "previous_agent"    # or a role name from `roles`
    dispatch: bool = True
    prompt: str = "integration_failed"


class IntegrateSpec(BaseModel):
    """Branch-integration policy (workflow slice 2). POLICY lives here in
    config; the ACTION is deterministic daemon code (daemon/integrate.py —
    merge --no-ff in the shared clone, push origin)."""
    # "" = the task's repo default_branch (Loop v1 C5). Never a literal main:
    # a fork/branch-based project (e.g. main-rsi) must not merge into main.
    target_branch: str = ""
    push: bool = True
    verify: VerifySpec = Field(default_factory=VerifySpec)
    on_failure: IntegrationFailureSpec = Field(default_factory=IntegrationFailureSpec)


class OnSuccess(BaseModel):
    """What the driver does when a run succeeds in a column."""
    advance_to: str
    assign_role: Optional[str] = None
    dispatch: bool = False
    # When set, the advance is two-phase: the daemon merges the task branch
    # per this policy first; the task only advances when the merge succeeds.
    integrate: Optional[IntegrateSpec] = None


class OnEnter(BaseModel):
    """What happens when a task ARRIVES in a column via the driver (slice 3:
    done -> dispatch the documentation role on the freshly merged task)."""
    dispatch_role: Optional[str] = None
    # On a HUMAN move into this column (manual_move.dispatch): start the
    # task's assigned agent on it (the work column has no hand-off role).
    dispatch_assignee: bool = False


class ManualMoveSpec(BaseModel):
    """What a HUMAN moving a task into a column triggers. dispatch=True →
    the column's agent is dispatched with the column's prompt: the role that
    enters the column (on_success.assign_role of the column before it, or
    on_enter.dispatch_role), else the assignee when on_enter.dispatch_assignee.
    Agent/workflow moves never trigger it — those paths dispatch themselves."""
    dispatch: bool = False


class ColumnSpec(BaseModel):
    name: str
    on_success: Optional[OnSuccess] = None
    on_enter: Optional[OnEnter] = None

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
    # Hand-off prompt file (templates/workflow/prompts/<prompt>.md). Empty ->
    # defaults to the role's own name (e.g. role "reviewer" -> reviewer.md).
    prompt: str = ""

    @validator("fallback")
    def fallback_known(cls, v):  # noqa: N805
        if v not in ("any", "none"):
            raise ValueError("fallback must be 'any' or 'none'")
        return v


class BounceSpec(BaseModel):
    """AP-231 self-correction policy (config, not constants). When a run
    succeeds but the advance gate fails, re-dispatch the same agent up to
    `max_attempts` total runs (on this task, in the window) before escalating
    to needs-attention. enabled=False disables the bounce entirely (the
    Conductor's progress watchdog is then the only recovery)."""
    enabled: bool = True
    max_attempts: int = 2          # original run + one corrective bounce
    window_minutes: int = 30


class RejectionSpec(BaseModel):
    """AP-252 rejection hand-back policy (config, not constants). When a task
    is deliberately demoted during a run, route it to whoever owes the fix.
    `assign`: 'previous_agent' (the implementer whose work was judged) or a
    role name from `roles`. Hand-backs share the bounce budget (no ping-pong).
    """
    enabled: bool = True
    assign: str = "previous_agent"
    dispatch: bool = True
    prompt: str = "rejection_handback"


class Workflow(BaseModel):
    columns: list[ColumnSpec]
    roles: dict[str, RoleSpec] = Field(default_factory=dict)
    bounce: BounceSpec = Field(default_factory=BounceSpec)
    rejection: RejectionSpec = Field(default_factory=RejectionSpec)
    manual_move: ManualMoveSpec = Field(default_factory=ManualMoveSpec)

    @validator("columns")
    def columns_not_empty(cls, v):  # noqa: N805
        if not v:
            raise ValueError("workflow must define at least one column")
        return v

    @model_validator(mode="after")
    def integration_failure_targets_exist(self):
        """A hand-back column named in config must be a real column — a typo
        would otherwise strand tasks at runtime."""
        names = {c.name for c in self.columns}
        for c in self.columns:
            ispec = c.on_success.integrate if c.on_success else None
            if ispec and ispec.on_failure.hand_back_on \
                    and ispec.on_failure.to_column not in names:
                raise ValueError(
                    f"integrate.on_failure.to_column "
                    f"'{ispec.on_failure.to_column}' is not a column")
        return self

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


def _gate_evidence_snapshot(task: Task) -> dict:
    """The task field values the AP-158 local gates read — same shape as
    backend.tasks._gate_evidence_snapshot, kept local to avoid a cross-module
    import for a 4-field dict."""
    return {
        "dod_items": task.dod_items,
        "assignee": task.assignee,
        "branch": task.branch,
        "pr_url": task.pr_url,
    }


def _already_handed_off(db, run: Run, task: Task) -> bool:
    """AP-402 idempotency guard: skip if the driver already recorded a
    decision for THIS run.

    Previously inferred from Run.created_at ("does a newer run exist on this
    task?") — a race between two finish_run calls landing close together
    could misjudge that ordering and deadlock the pipeline. Now it's an
    explicit fact: has a transition_events row with cause="run:<run.id>"
    already been written THIS turn? Scoped to the turn because sticky run rows
    are reused (AP-383 deadlock: a decision from the row's earlier turn
    skipped every later finish)."""
    return transitions_repo.has_driver_event_for_run(
        db, task_id=task.id, run_id=run.id, since=_turn_started_at(run))


def _turn_started_at(run: Run):
    """When the run's CURRENT turn began. Sticky rows (AP-281) keep their
    created_at forever; started_at is re-stamped on every turn."""
    return run.started_at or run.created_at


def _is_handoff_run(db, run: Run, task: Task) -> bool:
    """AP-520: a run that follows ANOTHER agent's succeeded run on the task
    (e.g. the reviewer's) is a hand-off — the work lives on that earlier
    agent's branch, not on this run's own worktree branch."""
    return runs_repo.prior_succeeded_run_by_other_agent(
        db, task_id=task.id, before=run.created_at,
        not_agent_id=run.agent_id) is not None


def _adopt_work_branch(db, run: Run, task: Task) -> None:
    """AP-521: task.branch is set-if-empty from the FIRST run's worktree
    branch. If that run never succeeded (e.g. out of credits), the task stays
    pinned to an empty branch — repoint it to this succeeded work run's
    branch. A branch no run produced (human/PR link) or one a run succeeded
    on is never touched."""
    new = (run.worktree_branch or "").strip()
    cur = (task.branch or "").strip()
    if not new or not cur or new == cur or _is_handoff_run(db, run, task):
        return
    outcomes = runs_repo.outcomes_for_branch(db, task_id=task.id, branch=cur)
    if not outcomes or RunOutcome.SUCCEEDED in outcomes:
        return
    logger.info("workflow: %s branch %s -> %s (earlier run on it never "
                "succeeded)", task.key or task.id, cur, new)
    task.branch = new
    db.commit()


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


def _entry_role(flow: "Workflow", column_name: str) -> str | None:
    """The role dispatched INTO a column: the preceding column's
    on_success.assign_role, else the column's own on_enter.dispatch_role."""
    for col in flow.columns:
        s = col.on_success
        if s and s.advance_to == column_name and s.assign_role:
            return s.assign_role
    col = flow.column(column_name)
    return col.on_enter.dispatch_role if col and col.on_enter else None


def _agent_named(db, name: str | None) -> Agent | None:
    if not name:
        return None
    return db.query(Agent).filter(Agent.name == name).first()


def dispatch_on_manual_move(task_id: str, to_status: str, actor: str) -> dict:
    """A HUMAN moved a task into `to_status`: dispatch that column's agent
    with the column's prompt, per `manual_move` + `on_enter` in the workflow
    config. Agent and workflow moves are ignored (they dispatch themselves).
    Never raises into the move."""
    try:
        with SessionLocal() as db:
            if actor in ("workflow", "system") or _agent_named(db, actor):
                return {"dispatched": False, "reason": "not_a_human_move"}
            task = db.get(Task, task_id)
            if not task:
                return {"dispatched": False, "reason": "task_gone"}
            project = db.get(Project, task.project_id) if task.project_id else None
            if not project or not getattr(project, "workflow_enabled", False):
                return {"dispatched": False, "reason": "workflow_disabled"}
            flow = effective_workflow(project)
            if not flow.manual_move.dispatch:
                return {"dispatched": False, "reason": "policy_off"}
            if runs_repo.has_active_run(db, task.id):
                return {"dispatched": False, "reason": "run_active"}
            col = flow.column(to_status)
            assignee = _agent_named(db, task.assignee)
            role_name = _entry_role(flow, to_status)
            agent, prompt = None, ""
            if role_name and role_name in flow.roles:
                role = flow.roles[role_name]
                matches = [m.lower() for m in role.match]
                if assignee and any(m in (assignee.name or "").lower() for m in matches):
                    agent = assignee
                else:
                    agent = pick_role_agent(
                        db, project_id=task.project_id, role=role,
                        previous_agent_id=assignee.id if assignee else None)
                prompt = _role_handoff_prompt(
                    flow, role_name, overrides=_prompt_overrides(project),
                    branch=task.branch or "", pr_url=task.pr_url or "")
            elif col and col.on_enter and col.on_enter.dispatch_assignee:
                agent = assignee
            if agent is None:
                return {"dispatched": False, "reason": "no_agent"}
            agent_id, agent_name = agent.id, agent.name
            reassign = agent_name != task.assignee
        if reassign:
            from backend import services as core_task_services
            core_task_services.update_task(task_id, assignee=agent_name,
                                           actor="workflow")
        from backend.forge import services
        d = services.schedule_task_run(task_id=task_id, agent_id=agent_id,
                                       extra_context=prompt)
        if isinstance(d, dict) and d.get("error"):
            logger.warning("workflow: manual-move dispatch failed %s -> %s: %s",
                           task_id, agent_name, d["error"])
            return {"dispatched": False, "reason": "dispatch_error",
                    "error": d["error"]}
        return {"dispatched": True, "agent": agent_name,
                "run_id": d.get("run_id") if isinstance(d, dict) else None}
    except Exception as exc:  # noqa: BLE001 — never break a move
        logger.exception("workflow.dispatch_on_manual_move failed %s: %s",
                         task_id, exc)
        return {"dispatched": False, "reason": "exception"}


def _bounce_gate_failure(db, *, task, run, current: str, target: str,
                         fails: list, policy: "BounceSpec") -> dict:
    """AP-231: a run declared `succeeded` but the advance gate failed —
    resolve the contradiction instead of stalling silently.

    1. Post the missing evidence on the task feed (always — visibility).
    2. Bounce: re-dispatch the same agent with a corrective prompt (config:
       templates/workflow/prompts/gate_bounce.md) up to `policy.max_attempts`
       total runs on this task in `policy.window_minutes`.
    3. Once that budget is spent (or bounce disabled), escalate: needs-
       attention comment + admin notification. The Conductor's progress
       watchdog (planning turn) is the intelligent layer that picks it up
       from there.

    The Run history is the bounce ledger — no new state, restart-proof.
    Returns a small dict merged into the driver's gate_failed result.
    """
    from backend.models import Activity
    reasons = "\n".join(f"- **{f.name}** — {f.reason or 'evidence missing'}"
                        for f in fails)
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=policy.window_minutes)
    recent_runs = (db.query(Run)
                     .filter(Run.task_id == task.id,
                             Run.agent_id == run.agent_id,
                             Run.created_at >= cutoff)
                     .count())
    task_id, task_key = task.id, (task.key or task.id)
    agent_id = run.agent_id

    if not policy.enabled or recent_runs >= policy.max_attempts:
        db.add(Activity(
            project_id=task.project_id, task_id=task.id, actor="workflow",
            action="commented",
            detail=(f"🚩 **Needs attention** — the run succeeded again but the "
                    f"task still can't advance {current}→{target}:\n{reasons}\n\n"
                    f"Automatic correction is exhausted; a human (or the "
                    f"Conductor) should look at this task."),
        ))
        db.commit()
        try:
            from backend.forge.services import _notify_admins
            _notify_admins(db, type_="workflow.needs_attention",
                           title=f"{task_key} can't advance: "
                                 f"{', '.join(f.name for f in fails)}",
                           link=f"/projects/{task.project_id}/tasks/{task.id}")
            db.commit()
        except Exception:  # noqa: BLE001 — best-effort
            pass
        logger.warning("workflow: %s bounce exhausted — escalated", task_key)
        return {"bounced": False, "escalated": True}

    db.add(Activity(
        project_id=task.project_id, task_id=task.id, actor="workflow",
        action="commented",
        detail=(f"↩️ **Bounced back to {task.assignee or 'the agent'}** — run "
                f"succeeded but the {current}→{target} gate failed:\n{reasons}\n\n"
                f"One corrective run dispatched to complete the evidence."),
    ))
    db.commit()

    project = db.get(Project, task.project_id) if task.project_id else None
    prompt = _resolve_prompt(project, "gate_bounce").replace("{{FAILURES}}", reasons)
    from backend.forge import services
    d = services.schedule_task_run(task_id=task_id, agent_id=agent_id,
                                   extra_context=prompt)
    if isinstance(d, dict) and d.get("error"):
        logger.warning("workflow: bounce dispatch failed %s: %s",
                       task_key, d["error"])
        return {"bounced": False, "bounce_error": d["error"]}
    logger.info("workflow: %s bounced to %s run=%s", task_key, agent_id,
                d.get("run_id") if isinstance(d, dict) else "?")
    return {"bounced": True,
            "bounce_run_id": d.get("run_id") if isinstance(d, dict) else None}


def _rejection_demotion(db, *, run: Run, task: Task,
                        flow: Workflow) -> dict | None:
    """AP-252: detect a deliberate BACKWARD move on the task during the run.

    A reviewer that rejects work demotes the task (review→in_progress) and
    unchecks DoD items — its run still finishes `succeeded` (the review WAS
    successful). The driver must recognize that demotion as intentional and
    NOT treat it as 'succeeded but can't advance' (which bounced a corrective
    run to the reviewer — the wrong agent).

    Evidence source: the Activity ledger (`task.move` rows carry a status
    diff). A rejection is a backward move whose DESTINATION lands the task in
    an implementer column BEFORE the review/integrate column — the reviewer
    handing work back to be fixed.

    AP-379/AP-383: a backward move INTO the review column (e.g. an operator
    manually moving done→review to force a re-review) is NOT a rejection — the
    task is sitting in review awaiting a verdict, and that verdict comes from
    the review RUN's typed evidence (`_human_approval_evidence`), never from how it entered
    the column. Reading done→review as a rejection bounced approved, mergeable
    PRs back to the implementer forever. So only moves landing strictly before
    the review column count. Returns {actor, from, to} or None.
    """
    from backend.forge.repos import activities as activities_repo
    order = {c.name: i for i, c in enumerate(flow.columns)}
    review_idx = next(
        (i for i, c in enumerate(flow.columns)
         if c.on_success and c.on_success.integrate is not None), None)
    moves = activities_repo.task_moves_since(
        db, task_id=task.id, since=_turn_started_at(run))
    for m in moves:
        try:
            diff = json.loads(m.diff or "{}").get("status") or {}
        except ValueError:
            continue
        src, dst = diff.get("from"), diff.get("to")
        if src not in order or dst not in order or order[dst] >= order[src]:
            continue
        # A move landing in the review/integrate column (or later) is a
        # re-review request, not a hand-back — let the run's own verdict decide.
        if review_idx is not None and order[dst] >= review_idx:
            continue
        return {"actor": m.actor, "from": src, "to": dst}
    return None


def _reviewer_name(db, run: Run) -> str | None:
    """The profile name of the run's own agent — the only actor whose review
    verdict counts for THIS review (server-injected, not prompt-writable)."""
    if not run.agent_id:
        return None
    agent = db.get(Agent, run.agent_id)
    profile = db.get(Profile, agent.profile_id) if agent and agent.profile_id else None
    return profile.name if profile else None


def _human_approval_evidence(db, *, run: Run, task: Task):
    """WFE Phase 2: the review verdict comes ONLY from typed evidence.

    Incident fix (2026-07-04, PR #167 merged before its review verdict): a run
    finishing `succeeded` in the review column proves only that the reviewer's
    SESSION completed cleanly — it is NOT approval. Approval is a structured
    `review_verdict` recorded by THIS run's own agent since it started; the old
    `REVIEW: APPROVE` comment-grep is gone (a forged comment now does nothing).
    Absent evidence blocks — silence is never approval."""
    from backend.forge import evidence
    return evidence.evaluate(
        "human_approval", task, db,
        ctx={"reviewer": _reviewer_name(db, run),
             "since": _turn_started_at(run)})


def _hand_back_after_rejection(db, *, task: Task, run: Run, flow: Workflow,
                               demotion: dict, feedback: str | None = None,
                               policy: "RejectionSpec | IntegrationFailureSpec | None" = None,
                               headline: str = "Review rejected",
                               ) -> dict:
    """AP-252: route a rejected task to whoever owes the fix.

    POLICY lives in config (`rejection:` in the workflow YAML): who gets the
    task back (`assign: previous_agent` or a role), whether a corrective run
    dispatches, and which prompt template carries the rejecter's feedback.
    This function is the deterministic ACTION. Budget-capped by the shared
    bounce policy so two agents can't ping-pong forever; exhausted (or no
    target resolvable) → needs-attention escalation.
    """
    from backend.forge.repos import activities as activities_repo
    from backend.forge.repos import runs as runs_repo
    # Review rejections use `rejection:`; integration failures pass their own
    # `integrate.on_failure:` policy (same fields: assign / dispatch / prompt).
    policy = policy or flow.rejection
    budget = flow.bounce
    task_key = task.key or task.id

    if not getattr(policy, "enabled", True):
        logger.info("workflow: %s demoted during run — rejection handling "
                    "disabled; leaving to the watchdog", task_key)
        return {"advanced": False, "reason": "review_rejected",
                "handed_back": False}

    impl: Agent | None = None
    if policy.assign == "previous_agent":
        prior = runs_repo.prior_run_by_other_agent(
            db, task_id=task.id, before=run.created_at,
            not_agent_id=run.agent_id)
        impl = db.get(Agent, prior.agent_id) if prior and prior.agent_id else None
    else:
        role = flow.roles.get(policy.assign)
        if role is not None:
            impl = pick_role_agent(db, project_id=task.project_id, role=role,
                                   previous_agent_id=run.agent_id)

    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=budget.window_minutes)
    impl_recent = (runs_repo.count_agent_runs_since(
        db, task_id=task.id, agent_id=impl.id, since=cutoff) if impl else 0)

    if impl is None or impl_recent >= budget.max_attempts:
        why = (f"no agent resolvable for rejection target "
               f"'{policy.assign}'" if impl is None
               else "correction budget exhausted")
        activities_repo.add_task_comment(
            db, project_id=task.project_id, task_id=task.id,
            detail=(f"🚩 **Needs attention** — review rejected this task "
                    f"({demotion['from']}→{demotion['to']} by "
                    f"{demotion['actor']}), but it can't be handed back "
                    f"automatically: {why}. A human should look at this."))
        db.commit()
        try:
            from backend.forge.services import _notify_admins
            _notify_admins(db, type_="workflow.needs_attention",
                           title=f"{task_key} rejected in review — {why}",
                           link=f"/projects/{task.project_id}/tasks/{task.id}")
            db.commit()
        except Exception:  # noqa: BLE001 — best-effort
            pass
        logger.warning("workflow: %s rejection hand-back escalated (%s)",
                       task_key, why)
        return {"advanced": False, "reason": "review_rejected",
                "escalated": True}

    # The reviewer's most recent comment is the corrective context.
    if feedback is None:
        review_note = activities_repo.latest_comment_by(
            db, task_id=task.id, actor=demotion["actor"], since=run.created_at)
        feedback = (review_note.detail if review_note
                    else "(no review comment found — re-read the task feed)")

    task_id, impl_id, impl_name = task.id, impl.id, impl.name
    from backend import services as core_task_services
    try:
        core_task_services.update_task(task_id, assignee=impl_name, actor="workflow")
    except PermissionError:
        # AP-374: the resolved hand-back target is no longer a project
        # member (e.g. removed since their prior run) — same "can't hand
        # back automatically" escalation as no-agent-resolvable, not a
        # silent reassignment.
        activities_repo.add_task_comment(
            db, project_id=task.project_id, task_id=task.id,
            detail=(f"🚩 **Needs attention** — review rejected this task "
                    f"({demotion['from']}→{demotion['to']} by "
                    f"{demotion['actor']}), but the hand-back target "
                    f"'{impl_name}' is no longer a project member. A human "
                    f"should look at this."))
        db.commit()
        logger.warning("workflow: %s rejection hand-back to %s blocked — "
                       "not a project member", task_key, impl_name)
        return {"advanced": False, "reason": "review_rejected",
                "escalated": True}
    activities_repo.add_task_comment(
        db, project_id=task.project_id, task_id=task.id,
        detail=(f"↩️ **{headline} — handed back to {impl.name}** "
                f"({demotion['from']}→{demotion['to']} by {demotion['actor']}). "
                f"Corrective run dispatched with the feedback."))
    db.commit()

    if not policy.dispatch:
        logger.info("workflow: %s rejected — reassigned to %s (no dispatch, "
                    "per policy)", task_key, impl_name)
        return {"advanced": False, "reason": "review_rejected",
                "handed_back": True, "assignee": impl_name}

    project = db.get(Project, task.project_id) if task.project_id else None
    prompt = (_resolve_prompt(project, policy.prompt)
              .replace("{{REVIEW}}", feedback))
    from backend.forge import services
    d = services.schedule_task_run(task_id=task_id, agent_id=impl_id,
                                   extra_context=prompt)
    if isinstance(d, dict) and d.get("error"):
        logger.warning("workflow: rejection hand-back dispatch failed %s: %s",
                       task_key, d["error"])
        return {"advanced": False, "reason": "review_rejected",
                "handed_back": False, "dispatch_error": d["error"]}
    logger.info("workflow: %s rejected — handed back to %s run=%s",
                task_key, impl_name,
                d.get("run_id") if isinstance(d, dict) else "?")
    return {"advanced": False, "reason": "review_rejected",
            "handed_back": True, "assignee": impl_name,
            "run_id": d.get("run_id") if isinstance(d, dict) else None}


# ── The driver ────────────────────────────────────────────────────────────

def _log_driver_decision(db, *, task: Task, run: Run, from_status: str | None,
                         to_status: str | None, result: str) -> None:
    """Every driver decision — advance or no-op alike — is a transition_events
    row, tied to the run that caused it (cause="run:<run.id>"). This is what
    makes `_already_handed_off` (AP-402) an explicit fact instead of a
    timestamp guess, and closes the "silent no-op" gap plan v4 §4 calls out."""
    transitions_repo.record_transition(
        db, task_id=task.id, from_status=from_status, to_status=to_status,
        actor_type="workflow", actor_id="driver",
        cause=f"run:{run.id}", result=result,
    )
    db.commit()


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
            _adopt_work_branch(db, run, task)
            project = db.get(Project, task.project_id) if task.project_id else None
            if not project or not getattr(project, "workflow_enabled", False):
                return {"advanced": False, "reason": "workflow_disabled"}
            if _already_handed_off(db, run, task):
                return {"advanced": False, "reason": "already_handed_off"}

            flow = effective_workflow(project)
            current = _status_name(db, task.status_id)

            # AP-252: a deliberate backward move during the run (reviewer
            # rejection, human demotion) means "do NOT advance" — the gate
            # failure that follows is intentional, not missing evidence. Hand
            # the task back to the implementer instead of bouncing the
            # reviewer.
            demotion = _rejection_demotion(db, run=run, task=task, flow=flow)
            if demotion:
                result = _hand_back_after_rejection(
                    db, task=task, run=run, flow=flow, demotion=demotion)
                _log_driver_decision(
                    db, task=task, run=run, from_status=current, to_status=None,
                    result=("handed_back" if result.get("handed_back")
                            else "escalated" if result.get("escalated")
                            else "no_op:rejection_handling_disabled"))
                return result

            col = flow.column(current) if current else None
            spec = col.on_success if col else None
            if not spec:
                _log_driver_decision(db, task=task, run=run, from_status=current,
                                     to_status=None, result="no_op:no_on_success")
                return {"advanced": False, "reason": f"no_on_success_for_{current}"}
            target = spec.advance_to

            # The driver respects the same evidence a manual move would —
            # except the PR-proxy gates when the flow integrates the branch
            # itself: gates exist to stop FAKED progress, and a system-performed
            # merge (verified by the daemon, conflict-aborted) is strictly
            # stronger evidence than a pr_url string. DoD gates still apply.
            import time as _time
            _started = _time.monotonic()
            all_results = gates.evaluate(task, from_status=current, to_status=target)
            fails = gates.failures(all_results)
            if spec.integrate is not None:
                fails = [f for f in fails
                         if f.name not in ("pr_url_set", "has_branch_or_pr")]
                # Terminal gate (plan v4 §5): merging requires >=1 typed
                # evidence.* condition. The human-approval fact is fetched from
                # the review_verdict store and its snapshot is persisted as its
                # OWN gate_evaluations row, so a merge-refusal is explainable
                # from recorded evidence — not a hidden driver decision.
                approval = _human_approval_evidence(db, run=run, task=task)
                transitions_repo.record_gate_evaluation(
                    db, task_id=task.id, from_status=current, to_status=target,
                    gate_id="evidence:human_approval",
                    evidence_snapshot={"human_approval": approval.to_dict()},
                    outcome="allow" if approval.present else "block",
                    reason="" if approval.present else approval.reason,
                    duration_ms=int((_time.monotonic() - _started) * 1000),
                )
                db.commit()
                if not approval.present:
                    from backend.models import Activity
                    db.add(Activity(
                        project_id=task.project_id, task_id=task.id,
                        actor="workflow", action="commented",
                        detail=("⛔ **Merge refused** — this run succeeded, but "
                                "no verified reviewer approval was found for "
                                "this task since the run started "
                                f"({approval.reason}). The branch stays "
                                "unmerged until the reviewer records an "
                                "approval verdict (`submit_review`)."),
                    ))
                    db.commit()
                    try:
                        from backend.forge.services import _notify_admins
                        _notify_admins(
                            db, type_="workflow.merge_refused",
                            title=f"{task.key or task.id}: merge refused — "
                                  f"no approval evidence",
                            link=f"/projects/{task.project_id}/tasks/{task.id}")
                        db.commit()
                    except Exception:  # noqa: BLE001 — best-effort
                        pass
                    logger.warning(
                        "workflow: %s merge refused — no approval evidence "
                        "(run=%s agent=%s)", task.key or task.id, run.id,
                        run.agent_id)
                    return {"advanced": False, "reason": "no_approval_evidence"}
            transitions_repo.record_gate_evaluation(
                db, task_id=task.id, from_status=current, to_status=target,
                gate_id=f"{current}:{target}",
                evidence_snapshot=_gate_evidence_snapshot(task),
                outcome="block" if fails else "allow",
                reason="; ".join(f.reason for f in fails),
                duration_ms=int((_time.monotonic() - _started) * 1000),
            )
            db.commit()
            if fails:
                logger.info("workflow: %s gate blocks %s->%s: %s",
                            task.key or task.id, current, target,
                            [f.name for f in fails])
                # AP-231: "succeeded but can't advance" must self-correct, not
                # silently stall. Surface the missing evidence + bounce the
                # task back to the same agent ONCE; then escalate loudly.
                bounce = _bounce_gate_failure(
                    db, task=task, run=run, current=current, target=target,
                    fails=fails, policy=flow.bounce)
                _log_driver_decision(
                    db, task=task, run=run, from_status=current, to_status=target,
                    result=("bounced" if bounce.get("bounced")
                            else "escalated" if bounce.get("escalated")
                            else "no_op:bounce_dispatch_failed"))
                return {"advanced": False, "reason": "gate_failed",
                        "failures": [f.name for f in fails], **bounce}

            target_status = db.query(Status).filter(Status.name == target).first()
            if not target_status:
                _log_driver_decision(db, task=task, run=run, from_status=current,
                                     to_status=target, result="no_op:unknown_column")
                return {"advanced": False, "reason": f"unknown_column_{target}"}

            # Two-phase advance (slice 2): when the column's policy says
            # `integrate`, the task branch must merge into the target branch
            # FIRST. The daemon owns the shared clone, so the merge happens
            # there; the advance completes in complete_integration() when the
            # daemon reports back. Conflict/push failure -> the task stays put
            # with a classified reason.
            if spec.integrate is not None:
                # AP-520: merge the task's WORK branch. The finishing run is
                # usually the reviewer's — its own worktree branch is empty.
                branch = (task.branch or "").strip()
                if not branch and not _is_handoff_run(db, run, task):
                    branch = (run.worktree_branch or "").strip()
                agent = db.get(Agent, run.agent_id) if run.agent_id else None
                runtime_id = agent.runtime_id if agent else None
                source_url = _task_source_url(db, task)
                ispec = spec.integrate
                target_branch = ispec.target_branch or _integration_target(db, task)
                verify_cmd = (getattr(project, "verify_cmd", None) or "").strip()
                if ispec.verify.required and not verify_cmd:
                    from backend.forge.repos import activities as activities_repo
                    activities_repo.add_task_comment(
                        db, project_id=task.project_id, task_id=task.id,
                        detail=("⛔ **Merge refused** — this project has no verify "
                                "command, so nothing proves the merged code works. "
                                "Set one in Project Settings → \"Command that "
                                "proves the project works\"."))
                    db.commit()
                    _log_driver_decision(
                        db, task=task, run=run, from_status=current, to_status=target,
                        result="no_op:no_verify_cmd")
                    return {"advanced": False, "reason": "no_verify_cmd"}
                timeout_min = (getattr(project, "verify_timeout_minutes", None)
                               or ispec.verify.default_timeout_minutes)
                if not branch or not runtime_id or not source_url or not target_branch:
                    _log_driver_decision(
                        db, task=task, run=run, from_status=current, to_status=target,
                        result="no_op:integration_missing_info")
                    return {"advanced": False, "reason": "integration_missing_info",
                            "branch": branch, "runtime": bool(runtime_id),
                            "source_url": bool(source_url),
                            "target": bool(target_branch)}
                task_id_, run_id_ = task.id, run.id
                _log_driver_decision(
                    db, task=task, run=run, from_status=current, to_status=target,
                    result="integration_requested")
                # Send outside the session via the captured app loop.
                from backend.forge.services import _dispatch_coro
                from backend.forge.ws_dispatch import hub
                _dispatch_coro(hub.dispatch_integrate(
                    runtime_id=runtime_id, task_id=task_id_, run_id=run_id_,
                    source_url=source_url, branch=branch,
                    target_branch=target_branch, push=ispec.push,
                    verify_cmd=verify_cmd, verify_timeout_s=60 * int(timeout_min),
                ))
                logger.info("workflow: %s integration requested (%s -> %s)",
                            task.key or task.id, branch, target_branch)
                return {"advanced": False, "integration_requested": True,
                        "branch": branch, "target": target_branch}

            next_agent = None
            if spec.assign_role:
                role = flow.roles.get(spec.assign_role)
                if role is None:
                    _log_driver_decision(
                        db, task=task, run=run, from_status=current, to_status=target,
                        result="no_op:role_undefined")
                    return {"advanced": False, "reason": "role_undefined",
                            "role": spec.assign_role}
                next_agent = pick_role_agent(
                    db, project_id=task.project_id, role=role,
                    previous_agent_id=run.agent_id)
                if next_agent is None:
                    logger.info("workflow: no agent for role=%s on %s — "
                                "not advancing", spec.assign_role,
                                task.key or task.id)
                    _log_driver_decision(
                        db, task=task, run=run, from_status=current, to_status=target,
                        result="no_op:no_role_agent")
                    return {"advanced": False, "reason": "no_role_agent",
                            "role": spec.assign_role}

            _log_driver_decision(db, task=task, run=run, from_status=current,
                                 to_status=target, result="advanced")
            db.commit()
            task_id, task_key = task.id, (task.key or task.id)
            task_branch, task_pr_url = task.branch or "", task.pr_url or ""
            next_agent_id = next_agent.id if next_agent else None
            next_agent_name = next_agent.name if next_agent else None
            prompt_overrides = _prompt_overrides(project)

        # Outside the session: route through TaskService so auth (AP-374),
        # gates, activity logging (AP-375), and agent wake all come from
        # the one place instead of a raw ORM write here.
        from backend import services as core_task_services
        core_task_services.move_task(task_id, target, actor="workflow",
                                     record_transition=False)
        if next_agent_name:
            core_task_services.update_task(task_id, assignee=next_agent_name,
                                           actor="workflow")

        result: dict = {"advanced": True, "to": target,
                        "assignee": next_agent_name}
        if spec.dispatch and next_agent_id:
            # Dispatch outside the session (schedule_task_run owns its own).
            # The Conductor tick only dispatches `todo` and skips tasks that
            # already have a run — hand-offs dispatch here. The dispatched
            # role gets its own hand-off instructions, not the bare
            # implementer prompt — column semantics must not depend on
            # agent persona (AP-361 review-worked-by-accident gap).
            handoff_prompt = _role_handoff_prompt(
                flow, spec.assign_role, overrides=prompt_overrides,
                branch=task_branch, pr_url=task_pr_url)
            from backend.forge import services
            d = services.schedule_task_run(task_id=task_id,
                                           agent_id=next_agent_id,
                                           extra_context=handoff_prompt)
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


def _task_source_url(db, task) -> str:
    """The git remote the task's branch lives in (mirrors dispatch's repo
    resolution: task.repo_name -> project repo row -> project.repo_url)."""
    from backend import services as core_services
    try:
        chosen = core_services.resolve_project_repo(
            task.project_id, getattr(task, "repo_name", None))
        if chosen and chosen.get("repo_url"):
            return chosen["repo_url"]
    except Exception:  # noqa: BLE001 — fall through to the project field
        pass
    project = db.get(Project, task.project_id)
    return (getattr(project, "repo_url", None) or "") if project else ""


def _integration_target(db, task) -> str:
    """The branch an approved task merges into: its repo's default_branch
    (task.repo_name → project repo row → legacy project fields). "" when
    unknown — the caller refuses rather than guessing."""
    from backend import services as core_services
    try:
        chosen = core_services.resolve_project_repo(
            task.project_id, getattr(task, "repo_name", None))
    except Exception:  # noqa: BLE001
        chosen = None
    return ((chosen or {}).get("default_branch") or "").strip()


def _record_tests_evidence(db, *, task, current: str | None, ok: bool,
                           reason: str, verify: dict) -> None:
    """The merged-tree check is evidence like any other: a gate_evaluations
    row + a plain-language line on the task (Loop v1 C6)."""
    transitions_repo.record_gate_evaluation(
        db, task_id=task.id, from_status=current, to_status=current,
        gate_id="evidence:tests", evidence_snapshot={"tests": verify},
        outcome="allow" if ok else "block", reason="" if ok else reason,
        duration_ms=int(float(verify.get("duration_s") or 0) * 1000))
    from backend.forge.repos import activities as activities_repo
    secs = verify.get("duration_s")
    if ok:
        line = f"🧪 Project checks passed on the merged code ({secs}s)."
    else:
        tail = "\n".join((verify.get("log_tail") or "").splitlines()[-40:])
        line = (f"🧪 Project checks **failed** on the merged code ({reason}). "
                f"Nothing was pushed.\n\n```\n{tail}\n```")
    activities_repo.add_task_comment(
        db, project_id=task.project_id, task_id=task.id, detail=line)
    db.commit()


def _failure_kind(reason: str) -> str:
    """The daemon's classified reason prefix, e.g. 'verify_failed: exit 1'."""
    return (reason or "").split(":", 1)[0].strip()


def complete_integration(*, task_id: str, run_id: str | None,
                         ok: bool, reason: str = "",
                         verify: dict | None = None) -> dict:
    """Finish a two-phase advance after the daemon reports the merge result.

    ok    -> advance the task to the column configured by its current
             column's on_success (no gate re-check: a system-performed merge
             is stronger evidence than the pr_url proxy the manual gate uses,
             and gates exist to stop FAKED progress — this isn't fakeable).
    !ok   -> leave the task where it is, surface the classified reason on the
             task feed, and notify admins (human-in-the-loop).
    """
    from backend.models import Activity
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            return {"ok": False, "error": "task_not_found"}
        project = db.get(Project, task.project_id) if task.project_id else None
        flow = effective_workflow(project) if project else system_workflow()
        current = _status_name(db, task.status_id)
        col = flow.column(current) if current else None
        spec = col.on_success if col else None

        if verify is not None:
            _record_tests_evidence(db, task=task, current=current, ok=ok,
                                   reason=reason, verify=verify)

        on_fail = spec.integrate.on_failure if spec and spec.integrate else None
        run = db.get(Run, run_id) if run_id else None
        if (not ok and on_fail is not None and run is not None
                and _failure_kind(reason) in on_fail.hand_back_on):
            # Config says this failure is the implementer's to fix: move the
            # task back and hand it over with the failure output.
            from backend import services as core_task_services
            core_task_services.move_task(task.id, on_fail.to_column, actor="workflow",
                                         skip_gates=True, record_transition=False)
            db.expire_all()
            task = db.get(Task, task_id)
            detail = (verify or {}).get("log_tail") or ""
            result = _hand_back_after_rejection(
                db, task=task, run=run, flow=flow,
                demotion={"actor": "workflow", "from": current,
                          "to": on_fail.to_column},
                feedback=f"{reason}\n\n{detail}".strip(), policy=on_fail,
                headline="Merge failed")
            transitions_repo.record_transition(
                db, task_id=task.id, from_status=current, to_status=on_fail.to_column,
                actor_type="workflow", actor_id="driver",
                cause=f"run:{run_id}", result="integration_handed_back")
            db.commit()
            logger.warning("workflow: integration failed task=%s (%s) — handed back",
                           task.key or task.id, reason)
            return {"ok": True, "advanced": False, "reason": reason, **result}

        if not ok:
            db.add(Activity(
                project_id=task.project_id, task_id=task.id, actor="workflow",
                action="commented",
                detail=(f"⛔ **Integration failed** — task stays in {current}.\n\n"
                        f"`{reason}`\n\nFix the branch (rebase/resolve) and "
                        f"re-run review to retry the merge."),
            ))
            db.commit()
            try:
                from backend.forge.services import _notify_admins
                _notify_admins(db, type_="workflow.integration_failed",
                               title=f"Merge failed for {task.key or task.id}: "
                                     f"{reason[:120]}",
                               link=f"/projects/{task.project_id}/tasks/{task.id}")
                db.commit()
            except Exception:  # noqa: BLE001 — best-effort notification
                pass
            transitions_repo.record_transition(
                db, task_id=task.id, from_status=current, to_status=None,
                actor_type="workflow", actor_id="driver",
                cause=f"run:{run_id}" if run_id else "integration_callback",
                result="integration_failed")
            db.commit()
            logger.warning("workflow: integration failed task=%s: %s",
                           task.key or task.id, reason)
            return {"ok": True, "advanced": False, "reason": reason}

        target = spec.advance_to if spec else "done"
        target_status = db.query(Status).filter(Status.name == target).first()
        if not target_status:
            return {"ok": False, "error": f"unknown_column_{target}"}
        transitions_repo.record_transition(
            db, task_id=task.id, from_status=current, to_status=target,
            actor_type="workflow", actor_id="driver",
            cause=f"run:{run_id}" if run_id else "integration_callback",
            result="advanced")
        db.commit()
        task_id_, task_key = task.id, (task.key or task.id)
        project_id_ = task.project_id
        merged_into = ((spec.integrate.target_branch if spec and spec.integrate else "")
                       or _integration_target(db, task))

        # TaskService, not a raw write: auth (AP-374), activity logging
        # (AP-375), and agent wake come from the one place. skip_gates=True
        # is the explicit re-entrancy escape hatch — the merge just
        # completed is stronger evidence than the pr_url/branch gates this
        # transition would otherwise re-check (see docstring above).
        from backend import services as core_task_services
        core_task_services.move_task(task_id_, target, actor="workflow",
                                     skip_gates=True, record_transition=False)
        core_task_services.add_comment(
            task_id_,
            (f"✅ **Integrated** — branch merged into "
             f"{merged_into or 'the base branch'} "
             f"and pushed. Task advanced to **{target}**."),
            actor="workflow",
        )

        # Slice 3: the target column's on_enter may dispatch a follow-up role
        # — done dispatches `documentation` so docs are written AFTER review,
        # about what actually merged. Skipped silently when the project has
        # no matching agent (fallback: none).
        doc_agent_id = doc_agent_name = doc_role = None
        target_col = flow.column(target)
        enter = target_col.on_enter if target_col else None
        if enter and enter.dispatch_role:
            role = flow.roles.get(enter.dispatch_role)
            if role is not None:
                a = pick_role_agent(db, project_id=project_id_, role=role,
                                    previous_agent_id=None)
                if a is not None:
                    doc_agent_id, doc_agent_name = a.id, a.name
                    doc_role = enter.dispatch_role
        task_branch, task_pr_url = task.branch or "", task.pr_url or ""
        prompt_overrides = _prompt_overrides(project)

    result = {"ok": True, "advanced": True, "to": target}
    if doc_agent_id:
        handoff_prompt = _role_handoff_prompt(
            flow, doc_role, overrides=prompt_overrides,
            branch=task_branch, pr_url=task_pr_url)
        from backend.forge import services
        d = services.schedule_task_run(task_id=task_id_, agent_id=doc_agent_id,
                                       extra_context=handoff_prompt)
        if isinstance(d, dict) and d.get("error"):
            logger.warning("workflow: docs dispatch failed %s -> %s: %s",
                           task_key, doc_agent_name, d["error"])
        else:
            result["docs_run_id"] = d.get("run_id") if isinstance(d, dict) else None
            result["docs_agent"] = doc_agent_name
    logger.info("workflow: %s integrated, advanced %s->%s docs=%s",
                task_key, current, target, doc_agent_name or "-")
    return result
