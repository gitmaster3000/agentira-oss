"""The Conductor — a special workspace-orchestrator agent (AP-80).

Unlike worker agents, the Conductor does not run code in a worktree.
It is the agent that *looks at the whole workspace* and hands todo work
to idle worker agents. It has:

  - an identity — the `Conductor` profile (seeded once, see
    `get_or_create_conductor`), so its actions are attributable;
  - a set of Python functions it acts through — `survey_workspace`,
    `pick_next_unblocked`, `run_tick`. These are the "tools" of the
    Conductor; a future revision can hand them to an LLM turn for
    smarter prioritisation instead of the FIFO pick used today.

It is active **workspace-wide** — every project, every conductor-enabled
worker agent — not bound to a single project.

## Runaway safety

The Conductor never double-dispatches a task with a **live** run (any
non-terminal `RunStatus`) and never re-dispatches a task whose latest run
**COMPLETED** — that success path belongs to the workflow driver (gate
advance/review), not re-dispatch. A task whose latest run is **FAILED** or
**CANCELLED** — e.g. it crashed, or a human/daemon stopped it — becomes
auto-pickable again once `conductor_redispatch_cooldown_minutes` has
elapsed since `finished_at`, and only up to `conductor_redispatch_max_attempts`
total runs on that task (config on the Conductor's own profile — see
`get_conductor_config`). This bounded recovery is what lets the loop heal
itself after a crash/cancel without a human re-triggering it, while still
capping the "schedules runs indefinitely" runaway case.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.db import SessionLocal
from backend.models import Profile, Project, Task, Status, Role
from backend.forge.models import Agent, Run, RunStatus, ForgeRuntime

logger = logging.getLogger("agentira.forge.conductor")

# Tick cadence (seconds) — each tick is one Conductor action.
TICK_INTERVAL_S = 60

# Runaway-guard recovery policy defaults (config, overridable per-Conductor —
# see get_conductor_config): a FAILED/CANCELLED task's run becomes eligible
# for auto-redispatch again after this cooldown, up to this many total runs.
REDISPATCH_COOLDOWN_MINUTES = 30
REDISPATCH_MAX_ATTEMPTS = 3

# Identity of the Conductor agent.
CONDUCTOR_NAME = "Conductor"

# Upper bound on rows a facts-gathering query pulls into memory in one go
# (gather_planning_facts, gather_progress_facts). These scan grows-forever
# tables (Task) on every tick/plan-interval; unbounded .all() would OOM the
# same way the unbounded /api/notifications history did (2026-07-04 incident).
FACTS_SCAN_LIMIT = 200

# Prompts are configuration, not code (AP-152/157): every Conductor prompt —
# the agent system prompt and the per-turn planning/report templates — lives
# as Markdown under `templates/`, OUTSIDE this module. Code only loads the
# file and fills in the dynamic facts. From backend/forge/conductor.py the
# repo-root `templates/` dir is three parents up.
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


def _load_prompt(relpath: str) -> str:
    """Read a prompt template (Markdown) from `templates/<relpath>`.

    Prompts are config — never inline a prompt string in Python. Raises if
    the file is missing; the templates ship with the repo, so absence is a
    packaging bug we want loud, not a silent in-code fallback prompt.
    """
    return (_TEMPLATES_DIR / relpath).read_text(encoding="utf-8")

# Last tick result — observability for the UI / status endpoint.
_LAST_TICK: dict | None = None


def get_last_tick() -> dict | None:
    """Most recent run_tick() result, or None if no tick has run yet."""
    return _LAST_TICK


# ── Identity ─────────────────────────────────────────────────────────────

# Default model for the Conductor. It is a normal agent field — change
# it in the agent config UI like any other agent.
CONDUCTOR_DEFAULT_MODEL = "claude-sonnet-4-5"

# The Conductor's role. code + LLM, split deliberately: the scripts
# (survey/find_free_agents/next_tasks/dispatch — exposed as MCP tools)
# gather facts and act for free; the LLM is spent only on judgment. The
# prompt prose itself is config, loaded from templates/ — never inline here.
def _conductor_system_prompt() -> str:
    """The Conductor's default system prompt, loaded from config.

    Seed default only — once a Conductor profile exists the DB/Agent
    Settings UI is the source of truth (set-if-empty, see AP-152).
    """
    return _load_prompt("conductor/system_prompt.md")


def get_or_create_conductor(org_id: str | None = None) -> dict:
    """Return the Conductor agent for an org, seeding it once if absent.

    Per-org: each org has its own Conductor. `org_id` defaults to the current
    request's org context; pass it explicitly when seeding a freshly-created
    org. The Conductor is a real LLM Agent — shows in the agent list, is
    configured (model, runtime, prompt) like any other agent.
    """
    import secrets
    from backend.db import get_current_org
    oid = org_id or get_current_org()
    with SessionLocal() as db:
        q = db.query(Profile).filter(Profile.name == CONDUCTOR_NAME)
        if oid:
            q = q.filter(Profile.org_id == oid)
        prof = q.first()
        if prof is None:
            role = db.query(Role).filter(Role.name == "member").first()
            if role is None:
                return {"error": "member role missing"}
            prof = Profile(
                name=CONDUCTOR_NAME, display_name="Conductor",
                password_hash="", avatar_url="", webhook_url="",
                account_type="agentira_agent", roles=[role],
                api_key=secrets.token_hex(32),
                org_id=oid,
            )
            db.add(prof)
            db.commit()
            db.refresh(prof)
            logger.info("Seeded Conductor profile %s (org %s)", prof.id, oid)

        # Bind a Claude runtime if one is registered, so the Conductor can
        # actually take an LLM turn. If none yet, leave it null — the
        # agent still exists and gets a runtime when a daemon registers.
        claude_rt = (db.query(ForgeRuntime)
                       .filter(ForgeRuntime.provider == "claude")
                       .first())
        rt_id = claude_rt.id if claude_rt else None

        # AP-152: prompts are configuration, not code. Seed the
        # Conductor's system_prompt ONCE on first create; never overwrite
        # a user-edited prompt with the code constant. The user owns the
        # agent's prompt from the moment it exists — Agent Settings UI is
        # the source of truth.
        if not prof.system_prompt:
            prof.system_prompt = _conductor_system_prompt()
        if not prof.model:
            prof.model = CONDUCTOR_DEFAULT_MODEL
        if rt_id and not prof.runtime_id:
            prof.runtime_id = rt_id
        prof.is_system = True

        agent = db.query(Agent).filter(Agent.id == prof.id).first()
        if agent is None:
            agent = Agent(
                id=prof.id, profile_id=prof.id, name=CONDUCTOR_NAME,
                executor_type="http", model=prof.model, runtime_id=rt_id,
                org_id=prof.org_id,
            )
            db.add(agent)
        elif rt_id and not agent.runtime_id:
            agent.runtime_id = rt_id
        db.commit()
        logger.info("Conductor agent ready: %s (model=%s runtime=%s)",
                    prof.id, prof.model, "set" if rt_id else "none")
        return {"id": prof.id, "name": prof.name,
                "model": prof.model, "runtime_bound": bool(rt_id)}


def get_conductor_config() -> dict:
    """Cadence config read off the Conductor's own profile.

    `tick_seconds` drives the deterministic queue-tick (dispatch);
    `report_time` / `report_enabled` drive the daily report;
    `plan_interval_minutes` drives the LLM planning turn (assignment).
    Falls back to module defaults if the Conductor isn't seeded yet.
    """
    with SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == CONDUCTOR_NAME).first()
        if not prof:
            return {"active": True, "tick_seconds": TICK_INTERVAL_S,
                    "report_time": "09:00", "report_enabled": True,
                    "plan_interval_minutes": 10,
                    "redispatch_cooldown_minutes": REDISPATCH_COOLDOWN_MINUTES,
                    "redispatch_max_attempts": REDISPATCH_MAX_ATTEMPTS}
        # Clamp the tick to a sane floor — a sub-10s tick would hammer the DB.
        tick = max(10, int(prof.conductor_tick_seconds or TICK_INTERVAL_S))
        # Planning turn costs tokens — floor it at 1 min.
        plan = max(1, int(prof.conductor_plan_interval_minutes or 10))
        cooldown = max(0, int(prof.conductor_redispatch_cooldown_minutes
                              or REDISPATCH_COOLDOWN_MINUTES))
        max_attempts = max(1, int(prof.conductor_redispatch_max_attempts
                                  or REDISPATCH_MAX_ATTEMPTS))
        return {"active": bool(prof.conductor_active),
                "tick_seconds": tick,
                "report_time": prof.conductor_report_time or "09:00",
                "report_enabled": bool(prof.conductor_report_enabled),
                "plan_interval_minutes": plan,
                "redispatch_cooldown_minutes": cooldown,
                "redispatch_max_attempts": max_attempts}


def _conductor_active() -> bool:
    """Master on/off, read off the Conductor profile. Default on."""
    with SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == CONDUCTOR_NAME).first()
        return bool(prof.conductor_active) if prof else True


# ── Picker ───────────────────────────────────────────────────────────────

def _todo_status_id(db) -> str | None:
    row = db.query(Status).filter(Status.name == "todo").first()
    return row.id if row else None


def _in_progress_status_id(db) -> str | None:
    row = db.query(Status).filter(Status.name == "in_progress").first()
    return row.id if row else None


def _backlog_status_id(db) -> str | None:
    row = db.query(Status).filter(Status.name == "backlog").first()
    return row.id if row else None


def _managed_projects(db) -> list[tuple[str, str]]:
    """Distinct (project_id, project_name) pairs with at least one
    conductor-enabled, project-bound agent — the set of projects the
    Conductor's turns iterate over, one turn per project (AP-4xx turn-
    scopes rework: a turn never mixes more than one project's facts)."""
    project_ids = {
        p.default_project_id
        for p in db.query(Profile)
                   .filter(Profile.conductor_enabled == True)  # noqa: E712
                   .filter(Profile.default_project_id.isnot(None))
                   .all()}
    if not project_ids:
        return []
    return [(p.id, p.name)
            for p in db.query(Project).filter(Project.id.in_(project_ids)).all()]


# Lower rank = dispatched first. Unknown/missing priority sorts as medium.
_PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# A task with a run in one of these statuses is "live" — never double-dispatch.
# READY is deliberately absent: it is a prepared draft awaiting a start (what
# assignment creates), not work in flight — it must not block the Conductor
# (AP-478 / Loop v1 C1).
_ACTIVE_RUN_STATUSES = {RunStatus.PENDING, RunStatus.RUNNING,
                        RunStatus.INTERRUPTING, RunStatus.PAUSED}
# Terminal statuses eligible for bounded auto-recovery (cooldown + attempt
# cap). COMPLETED is deliberately excluded — the workflow driver owns
# post-success flow, not re-dispatch.
_RECOVERABLE_RUN_STATUSES = {RunStatus.FAILED, RunStatus.CANCELLED}


def _redispatch_policy() -> tuple[int, int]:
    """(cooldown_minutes, max_attempts) for auto-recovering a FAILED/
    CANCELLED task's auto-pickup — config off the Conductor's own profile,
    never hardcoded (see get_conductor_config)."""
    cfg = get_conductor_config()
    return cfg["redispatch_cooldown_minutes"], cfg["redispatch_max_attempts"]


def _run_status(run: Run) -> RunStatus | None:
    if run.status is None:
        return None
    return run.status if isinstance(run.status, RunStatus) else RunStatus(run.status)


def _task_run_eligible(db, task_id: str, latest_run: "Run | None", *,
                       cooldown_minutes: int, max_attempts: int,
                       agent_id: str | None = None) -> bool:
    """Is this task's run state one the Conductor may auto-pick right now?

    No run at all -> fresh task, always eligible. A live (non-terminal) run
    -> never eligible (never double-dispatch). COMPLETED -> never eligible
    again (workflow driver's job). FAILED/CANCELLED -> eligible once the
    cooldown since finished_at has elapsed AND the attempt budget isn't
    spent — this is the crash/cancel self-healing path.
    """
    if latest_run is None:
        return True
    status = _run_status(latest_run)
    if status == RunStatus.READY:
        # A prepared draft: schedule_task_run reuses this row and starts it.
        return agent_id is None or latest_run.agent_id == agent_id
    if status not in _RECOVERABLE_RUN_STATUSES:
        return False
    from backend.forge.repos import runs as runs_repo
    if runs_repo.count_runs_for_task(db, task_id) >= max_attempts:
        return False
    # Same fallback chain as the progress watchdog (_run_last_activity):
    # finished_at, or the closest thing to it, so a run with a gap in its
    # timestamps still gets a real cooldown instead of skipping it.
    elapsed = datetime.now(timezone.utc) - _run_last_activity(latest_run)
    return elapsed >= timedelta(minutes=cooldown_minutes)


def _recovery_note(db, task_id: str, max_attempts: int) -> str | None:
    """If this pick is a crash/cancel recovery (the task's latest prior run
    was FAILED/CANCELLED), a human-readable task-feed note — else None for a
    normal fresh dispatch. Lets a human see the loop healed itself and how
    many auto-redispatch attempts have been burned."""
    from backend.forge.repos import runs as runs_repo
    prior = runs_repo.latest_runs_by_task(db, [task_id]).get(task_id)
    if prior is None:
        return None
    status = _run_status(prior)
    if status not in _RECOVERABLE_RUN_STATUSES:
        return None
    attempts = runs_repo.count_runs_for_task(db, task_id)
    return (f"🔁 **Auto-recovered** — the previous run ended `{status.value}`; "
            f"the Conductor re-dispatched this task automatically "
            f"(attempt {attempts + 1}/{max_attempts}).")


def _dispatch_note(agent_name: str) -> str:
    """The task-feed line every Conductor dispatch leaves (transparency)."""
    return f"▶️ Conductor dispatched this task to **{agent_name}**."


def pick_next_unblocked(*, project_id: str, agent_id: str, db=None) -> "Task | None":
    """Return the next eligible todo task ASSIGNED to `agent_id` in `project_id`.

    Eligible: status == 'todo', assignee == this agent (exact name), AND its
    run state passes `_task_run_eligible` — no run yet, or a FAILED/CANCELLED
    run past its cooldown with attempt budget left. A live or COMPLETED run
    disqualifies the task; that's the runaway guard (see module docstring).

    Assigned-only is deliberate (the "intelligent dispatch" contract): the LLM
    planning turn owns *who* gets *what* via `update_task(assignee=…)`; this
    deterministic tick only dispatches what the planner already assigned. It no
    longer FIFO-grabs unassigned tasks — that front-ran the planner's judgment.

    Ordered by priority (critical→low) then created_at, so an agent's highest-
    priority assigned work goes first. Caller owns the session if one is passed.
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        todo_id = _todo_status_id(db)
        if not todo_id:
            return None
        agent = db.get(Agent, agent_id)
        if not agent:
            return None
        from backend.forge.repos import runs as runs_repo
        from backend.forge.repos import tasks as tasks_repo
        rows = tasks_repo.todo_candidates(
            db, project_id=project_id, status_id=todo_id, assignee=agent.name)
        if not rows:
            return None
        cooldown_minutes, max_attempts = _redispatch_policy()
        latest_by_task = runs_repo.latest_runs_by_task(db, [t.id for t in rows])
        rows = [t for t in rows
                if _task_run_eligible(db, t.id, latest_by_task.get(t.id),
                                      cooldown_minutes=cooldown_minutes,
                                      max_attempts=max_attempts,
                                      agent_id=agent_id)]
        if not rows:
            return None
        # Stable sort by priority; created_at order is preserved within a tier.
        # Sorted in Python to stay agnostic of how the priority enum is stored.
        def _rank(t):
            p = t.priority.value if hasattr(t.priority, "value") else str(t.priority)
            return _PRIORITY_RANK.get(p, 2)
        rows.sort(key=_rank)
        return rows[0]
    finally:
        if own_session:
            db.close()


def _agent_in_flight_count(db, agent_id: str) -> int:
    """Runs for this agent in a non-terminal state."""
    return (db.query(Run)
              .filter(Run.agent_id == agent_id,
                      Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING,
                                      RunStatus.PAUSED]))
              .count())


# ── Survey + tick ────────────────────────────────────────────────────────

def survey_workspace() -> dict:
    """Read-only snapshot the Conductor reasons over: every conductor-
    enabled worker agent, its in-flight load, and its next eligible task.

    Exposed as a function (and via the status endpoint) so a UI — or a
    future LLM Conductor turn — can see the same picture run_tick acts on.
    """
    agents_view: list[dict] = []
    with SessionLocal() as db:
        profiles = (db.query(Profile)
                      .filter(Profile.conductor_enabled == True)  # noqa: E712
                      .filter(Profile.default_project_id.isnot(None))
                      .all())
        for prof in profiles:
            agent = db.query(Agent).filter(Agent.profile_id == prof.id).first()
            if not agent:
                continue
            inflight = _agent_in_flight_count(db, agent.id)
            cap = max(1, int(prof.max_concurrent_runs or 1))
            nxt = None
            if inflight < cap:
                t = pick_next_unblocked(
                    project_id=prof.default_project_id, agent_id=agent.id, db=db)
                nxt = {"id": t.id, "title": t.title} if t else None
            agents_view.append({
                "agent": agent.id, "name": agent.name,
                "project_id": prof.default_project_id,
                "in_flight": inflight, "capacity": cap,
                "next_task": nxt,
                "specialty": _agent_specialty(prof),
            })
    return {"agents": agents_view}


def run_tick() -> dict:
    """One Conductor action — workspace-wide.

    For each conductor-enabled worker agent below its concurrency cap,
    picks its next FRESH todo task, dispatches it, and moves the task to
    in_progress so it is claimed exactly once. Per-agent failures are
    logged and skipped — one bad row must not stall the fleet.

    Zombie-run reconciliation (AP-119) lives solely in
    `backend.forge.reconciler.reconcile_stale_runs`, scheduled independently
    every `reconciler.RECONCILE_INTERVAL_S` — this tick used to run its own
    duplicate sweep of the same non-terminal runs; that duplicate was
    removed (2026-07-04 query-hygiene sweep) in favor of the single,
    heartbeat-based reconciler.
    """
    global _LAST_TICK
    if not _conductor_active():
        # Keep the same shape as a normal tick — `skipped` is always the
        # list of skipped-agent records; `disabled` is the off marker.
        _LAST_TICK = {"disabled": True, "dispatched": [], "skipped": []}
        return _LAST_TICK
    dispatched: list[dict] = []
    skipped: list[dict] = []

    with SessionLocal() as db:
        in_progress_id = _in_progress_status_id(db)
        profiles = (db.query(Profile)
                      .filter(Profile.conductor_enabled == True)  # noqa: E712
                      .filter(Profile.default_project_id.isnot(None))
                      .all())
        for prof in profiles:
            agent = db.query(Agent).filter(Agent.profile_id == prof.id).first()
            if not agent:
                skipped.append({"profile": prof.id, "reason": "no_agent"})
                continue
            if not agent.runtime_id:
                skipped.append({"agent": agent.id, "reason": "no_runtime"})
                continue
            cap = max(1, int(prof.max_concurrent_runs or 1))
            inflight = _agent_in_flight_count(db, agent.id)
            if inflight >= cap:
                skipped.append({"agent": agent.id, "reason": "at_capacity",
                                "inflight": inflight, "cap": cap})
                continue
            task = pick_next_unblocked(
                project_id=prof.default_project_id, agent_id=agent.id, db=db)
            if not task:
                skipped.append({"agent": agent.id, "reason": "no_eligible_task"})
                continue
            _, max_attempts = _redispatch_policy()
            recovery_note = _recovery_note(db, task.id, max_attempts)
            try:
                from backend.forge import services
                result = services.schedule_task_run(task_id=task.id, agent_id=agent.id)
                if isinstance(result, dict) and result.get("error"):
                    logger.warning("Conductor dispatch error agent=%s task=%s: %s",
                                   agent.id, task.id, result["error"])
                    skipped.append({"agent": agent.id, "task": task.id,
                                    "reason": "dispatch_error", "error": result["error"]})
                    continue
                # Claim the task — move todo -> in_progress so it is never
                # auto-picked again even though it now also has a run.
                if in_progress_id:
                    db.query(Task).filter(Task.id == task.id).update(
                        {"status_id": in_progress_id})
                    db.commit()
                from backend.forge.repos import activities as activities_repo
                activities_repo.add_task_comment(
                    db, project_id=prof.default_project_id, task_id=task.id,
                    detail=_dispatch_note(agent.name), actor=CONDUCTOR_NAME)
                db.commit()
                if recovery_note:
                    activities_repo.add_task_comment(
                        db, project_id=prof.default_project_id, task_id=task.id,
                        detail=recovery_note, actor=CONDUCTOR_NAME)
                    db.commit()
                    logger.info("Conductor recovered task=%s (%s)", task.id, recovery_note)
                dispatched.append({
                    "agent": agent.id, "task": task.id,
                    "run_id": result.get("run_id") if isinstance(result, dict) else None,
                })
                logger.info("Conductor dispatched agent=%s task=%s", agent.id, task.id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Conductor tick failed for agent=%s: %s", agent.id, exc)
                skipped.append({"agent": agent.id, "reason": "exception", "error": str(exc)})

    _LAST_TICK = {"dispatched": dispatched, "skipped": skipped}
    return _LAST_TICK


def tick_agent(agent_id: str) -> dict:
    """Event-driven scheduling: dispatch THIS agent's next assigned todo task
    the moment it frees up (terminal run), instead of waiting for the next
    poll. The agent loop becomes free → pull next → busy → free with no idle
    gap between ticks; the periodic run_tick stays as the reconciliation
    safety net (missed events, daemon drops, restarts).

    Same guards as run_tick, scoped to one agent: master switch, conductor-
    enabled + project-bound profile, capacity (the per-agent counting
    semaphore: in-flight < max_concurrent_runs), assigned-only picker.
    Token-free; never raises into the caller."""
    try:
        if not _conductor_active():
            return {"dispatched": False, "reason": "conductor_disabled"}
        with SessionLocal() as db:
            agent = db.get(Agent, agent_id)
            if not agent or not agent.runtime_id:
                return {"dispatched": False, "reason": "no_agent_or_runtime"}
            prof = (db.get(Profile, agent.profile_id)
                    if agent.profile_id else None)
            if (not prof or not prof.conductor_enabled
                    or not prof.default_project_id):
                return {"dispatched": False, "reason": "not_conductor_managed"}
            cap = max(1, int(prof.max_concurrent_runs or 1))
            if _agent_in_flight_count(db, agent_id) >= cap:
                return {"dispatched": False, "reason": "at_capacity"}
            task = pick_next_unblocked(
                project_id=prof.default_project_id, agent_id=agent_id, db=db)
            if not task:
                return {"dispatched": False, "reason": "no_eligible_task"}
            task_id = task.id
            agent_name = agent.name
            project_id = prof.default_project_id
            in_progress_id = _in_progress_status_id(db)
            _, max_attempts = _redispatch_policy()
            recovery_note = _recovery_note(db, task_id, max_attempts)

        from backend.forge import services
        result = services.schedule_task_run(task_id=task_id, agent_id=agent_id)
        if isinstance(result, dict) and result.get("error"):
            return {"dispatched": False, "reason": "dispatch_error",
                    "error": result["error"]}
        # Claim — same as run_tick: in_progress + a Run row each disqualify
        # the task from ever being auto-picked again.
        with SessionLocal() as db:
            if in_progress_id:
                db.query(Task).filter(Task.id == task_id).update(
                    {"status_id": in_progress_id})
                db.commit()
            from backend.forge.repos import activities as activities_repo
            activities_repo.add_task_comment(
                db, project_id=project_id, task_id=task_id,
                detail=_dispatch_note(agent_name), actor=CONDUCTOR_NAME)
            db.commit()
            if recovery_note:
                activities_repo.add_task_comment(
                    db, project_id=project_id, task_id=task_id,
                    detail=recovery_note, actor=CONDUCTOR_NAME)
                db.commit()
                logger.info("tick_agent recovered task=%s (%s)", task_id, recovery_note)
        logger.info("tick_agent dispatched agent=%s task=%s", agent_id, task_id)
        return {"dispatched": True, "task": task_id,
                "run_id": result.get("run_id") if isinstance(result, dict) else None}
    except Exception as exc:  # noqa: BLE001 — scheduling must not break callers
        logger.exception("tick_agent failed for %s: %s", agent_id, exc)
        return {"dispatched": False, "reason": "exception", "error": str(exc)}


# ── Daily report — the Conductor's one scheduled LLM turn ────────────────
#
# The queue tick (above) is deterministic and token-free — that's by
# design. The judgment work — reviewing progress, naming blockers,
# recommending priorities — is where an LLM earns its tokens. So the
# Conductor takes exactly one LLM turn a day: facts are gathered by
# scripts (free), then handed to the Conductor agent to write the report.

# Most recent daily-report result — observability for the status endpoint.
_LAST_REPORT: dict | None = None


def get_last_report() -> dict | None:
    return _LAST_REPORT


def gather_report_facts() -> dict:
    """Deterministic, token-free workspace snapshot for the daily report:
    a per-project 24h digest plus the agent survey. No LLM, no mutation."""
    from backend.forge.digest import generate_digest
    with SessionLocal() as db:
        projects = [(p.id, p.name) for p in db.query(Project).all()]

    project_facts: list[dict] = []
    for pid, pname in projects:
        d = generate_digest(project_id=pid, since="24h")
        if d.get("error"):
            continue
        c = d.get("counts", {})
        # Skip silent projects — keeps the report focused on real activity.
        if not any(c.values()):
            continue
        project_facts.append({
            "project": pname,
            "counts": c,
            "stats": d.get("stats", {}),
        })
    return {"projects": project_facts, "survey": survey_workspace()}


def _compose_report_prompt(facts: dict) -> str:
    """Fill the daily-report template (config) with the gathered facts.

    Code only serialises the facts into rows; all instruction prose —
    including the HTML structure spec — lives in
    templates/conductor/daily_report.md (prompts-are-config).
    """
    projects = facts.get("projects") or []
    if projects:
        proj_rows = "\n".join(
            f"- {p['project']}: {p['counts'].get('done', 0)} done, "
            f"{p['counts'].get('blocked', 0)} blocked, "
            f"{p['counts'].get('needs_input', 0)} needs-input, "
            f"{p['counts'].get('failed', 0)} failed, "
            f"{p['counts'].get('in_flight', 0)} in-flight "
            f"(${p['stats'].get('cost_usd', 0)})"
            for p in projects
        )
    else:
        proj_rows = "- No run activity."
    agents = (facts.get("survey") or {}).get("agents") or []
    if agents:
        agent_rows = "\n".join(
            f"- {a['name']}: {a['in_flight']}/{a['capacity']} in-flight; "
            f"next: {a['next_task']['title'] if a.get('next_task') else 'nothing queued'}"
            for a in agents
        )
    else:
        agent_rows = "- No conductor-enabled worker agents."
    return (_load_prompt("conductor/daily_report.md")
            .replace("{{PROJECTS}}", proj_rows)
            .replace("{{AGENTS}}", agent_rows))


def run_daily_report() -> dict:
    """Compile + post the Conductor's daily report.

    Facts are gathered token-free, then handed to the Conductor agent as
    a single LLM turn. The report lands in the Conductor's chat thread.
    Skips cleanly when the Conductor has no runtime or the report is
    disabled in config.
    """
    global _LAST_REPORT
    if not _conductor_active():
        _LAST_REPORT = {"skipped": "conductor_disabled"}
        return _LAST_REPORT
    with SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == CONDUCTOR_NAME).first()
        if not prof:
            _LAST_REPORT = {"skipped": "no_conductor"}
            return _LAST_REPORT
        if not prof.conductor_report_enabled:
            _LAST_REPORT = {"skipped": "report_disabled"}
            return _LAST_REPORT
        if not prof.runtime_id:
            _LAST_REPORT = {"skipped": "no_runtime"}
            logger.info("Daily report skipped — Conductor has no runtime.")
            return _LAST_REPORT
        conductor_id = prof.id

    facts = gather_report_facts()
    prompt = _compose_report_prompt(facts)
    # The daily report stays a global (workspace-wide) human digest — but
    # it still gets its own turn scope (never chat:default) and a durable
    # PlanningTurn record, same transparency contract as every other turn.
    turn_id = _record_planning_turn(
        trigger="daily_report", status="dispatched", facts=facts)
    scope_key = f"turn:{turn_id}"
    try:
        from backend.forge import services
        from backend.forge.repos import planning_turns as pt_repo
        services.send_runtime_message(
            conductor_id, content=prompt, scope_key=scope_key)
        with SessionLocal() as db:
            pt_repo.set_scope_key(db, turn_id, scope_key)
            db.commit()
        _LAST_REPORT = {"ok": True, "at": datetime.now(timezone.utc).isoformat(),
                        "projects": len(facts.get("projects") or [])}
        logger.info("Conductor daily report dispatched.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Daily report dispatch failed: %s", exc)
        with SessionLocal() as db:
            from backend.forge.repos import planning_turns as pt_repo
            pt_repo.update_status(db, turn_id, "error")
            db.commit()
        _LAST_REPORT = {"error": str(exc)}
    return _LAST_REPORT


# ── Planning turn — the LLM decides assignments ──────────────────────────
#
# The queue tick (deterministic) DISPATCHES assigned/unassigned todo work.
# The planning turn is where the LLM earns its tokens: it looks at the
# UNASSIGNED todo backlog + the available agents and sets each task's
# `assignee` (smart, judgment-based fit + load-balance). The next queue
# tick then dispatches per those assignments. Facts are gathered by a
# script (free); the LLM only decides; the actual dispatch stays in the
# deterministic tick. Runs only when there is unassigned work to plan.

_LAST_PLAN: dict | None = None


def get_last_plan() -> dict | None:
    return _LAST_PLAN


def _agent_specialty(prof) -> str:
    """A one-line specialty hint so the planner can skill-match. Prefer the
    explicit personality; else the first non-empty line of the system prompt.
    Capped so the planning facts stay token-cheap."""
    txt = (getattr(prof, "personality", "") or "").strip()
    if not txt:
        sp = (getattr(prof, "system_prompt", "") or "").strip()
        txt = next((ln.strip() for ln in sp.splitlines() if ln.strip()), "")
    return txt[:200]


def _task_fact(t: "Task") -> dict:
    """One task's planner-facing fact row: id/key/title/priority + a
    capped description (never the full text — see FACTS_SCAN_LIMIT note)."""
    return {
        "id": t.id, "key": t.key, "title": t.title,
        "project_id": t.project_id,
        "priority": t.priority.value if hasattr(t.priority, "value")
                    else (t.priority or "medium"),
        "description": (t.description or "")[:300],
    }


# Top-N backlog tasks considered for promotion in a single planning turn.
BACKLOG_PROMOTE_LIMIT = 30


def gather_planning_facts(project_id: str) -> dict:
    """Token-free snapshot for ONE project's planning turn (AP-4xx turn-
    scopes rework): the agents bound to this project (with specialty/model,
    so the planner can skill-match), its UNASSIGNED un-run todo tasks, its
    top backlog candidates (priority-ranked, capped), and the team's free
    capacity. Never mixes another project's agents/tasks into the facts —
    that isolation is the whole point of the per-project turn."""
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        project_name = project.name if project else project_id
        todo_id = _todo_status_id(db)
        backlog_id = _backlog_status_id(db)
        profiles = (db.query(Profile)
                      .filter(Profile.conductor_enabled == True)  # noqa: E712
                      .filter(Profile.default_project_id == project_id)
                      .all())
        agents: list[dict] = []
        for prof in profiles:
            a = db.query(Agent).filter(Agent.profile_id == prof.id).first()
            if not a:
                continue
            agents.append({
                "name": a.name,
                "project_id": prof.default_project_id,
                "in_flight": _agent_in_flight_count(db, a.id),
                "capacity": max(1, int(prof.max_concurrent_runs or 1)),
                "specialty": _agent_specialty(prof),
                "model": prof.model or "",
            })

        from backend.forge.repos import runs as runs_repo
        from backend.forge.repos import tasks as tasks_repo
        cooldown_minutes, max_attempts = _redispatch_policy()

        tasks: list[dict] = []
        if todo_id:
            rows = tasks_repo.unassigned_todo_candidates(
                db, project_ids=[project_id], status_id=todo_id,
                limit=FACTS_SCAN_LIMIT)
            latest_by_task = runs_repo.latest_runs_by_task(db, [t.id for t in rows])
            rows = [t for t in rows
                    if _task_run_eligible(db, t.id, latest_by_task.get(t.id),
                                          cooldown_minutes=cooldown_minutes,
                                          max_attempts=max_attempts)]
            tasks = [_task_fact(t) for t in rows]

        backlog: list[dict] = []
        if backlog_id:
            # Fetch a wide window, THEN rank by priority, THEN cap. Capping
            # at the repo layer (created_at order) would freeze the pool on
            # the N oldest tasks — a fresh critical task behind 30 stale
            # ones would never surface for promotion.
            rows = tasks_repo.backlog_candidates(
                db, project_id=project_id, status_id=backlog_id,
                limit=FACTS_SCAN_LIMIT)
            rows.sort(key=lambda t: _PRIORITY_RANK.get(
                t.priority.value if hasattr(t.priority, "value") else str(t.priority), 2))
            backlog = [_task_fact(t) for t in rows[:BACKLOG_PROMOTE_LIMIT]]

        capacity = sum(max(0, a["capacity"] - a["in_flight"]) for a in agents)

    return {
        "project_id": project_id, "project_name": project_name,
        "agents": agents, "unassigned_tasks": tasks,
        "backlog": backlog, "capacity": capacity,
    }


def _fenced(body: str) -> str:
    """Wrap task/agent listing rows in a fenced block — data, not
    instructions (section C injection guard)."""
    return f"```\n{body}\n```"


def _fmt_task_row(t: dict) -> str:
    return (f"- task_id={t['id']} [{t.get('key') or '?'}] "
            f"({t.get('priority') or 'medium'}) — {t['title']}"
            + (f"\n    {t['description']}" if t.get("description") else ""))


def _compose_turn_guard(project_name: str) -> str:
    """The authoritative injection-guard block prepended to every composed
    turn prompt (section C) — same pattern as templates/epic_planning."""
    return _load_prompt("conductor/turn_guard.md").replace(
        "{{PROJECT}}", project_name or "")


def _compose_planning_prompt(facts: dict) -> str:
    """Fill the planning-turn template (config) with the gathered facts.

    Code only serialises the facts into rows; all instruction prose lives
    in templates/conductor/planning_turn.md (prompts-are-config). Task
    rows are fenced (data, not instructions — section C).
    """
    project_name = facts.get("project_name") or facts.get("project_id") or ""
    agents = "\n".join(
        f"- {a['name']} ({a.get('model') or 'model?'}) — "
        f"{a['in_flight']}/{a['capacity']} in flight"
        + (f"\n    specialty: {a['specialty']}" if a.get("specialty") else "")
        for a in facts["agents"]
    ) or "- (none)"
    tasks = "\n".join(_fmt_task_row(t) for t in facts["unassigned_tasks"]) or "- (none)"
    backlog = "\n".join(_fmt_task_row(t) for t in facts.get("backlog") or []) or "- (none)"
    body = (_load_prompt("conductor/planning_turn.md")
            .replace("{{PROJECT}}", project_name)
            .replace("{{AGENTS}}", agents)
            .replace("{{TASKS}}", _fenced(tasks))
            .replace("{{BACKLOG}}", _fenced(backlog))
            .replace("{{CAPACITY}}", str(facts.get("capacity", 0))))
    return _compose_turn_guard(project_name) + "\n\n" + body


def _record_planning_turn(
    *, trigger: str, status: str, facts: dict, model: str | None = None,
    duration_ms: int | None = None, conversation_scope_key: str | None = None,
    decisions: list[dict] | None = None,
) -> str | None:
    """Persist a PlanningTurn row (AP-401 transparency record). Never raises
    into the caller — a logging failure must not break the planning turn."""
    try:
        from backend.forge.repos import planning_turns as pt_repo
        with SessionLocal() as db:
            row = pt_repo.create_planning_turn(
                db, trigger=trigger, status=status, model=model,
                duration_ms=duration_ms, facts_snapshot=facts,
                decisions=decisions, conversation_scope_key=conversation_scope_key)
            db.commit()
            return row.id
    except Exception:  # noqa: BLE001
        logger.exception("Failed to record planning turn (status=%s)", status)
        return None


def record_planning_decision(
    turn_id: str, *, action: str, reason: str, task_id: str | None = None,
    agent: str | None = None, project_id: str | None = None,
) -> None:
    """Append one decision to a PlanningTurn's durable record, e.g.
    `action="assigned"` / `"dispatched"` / `"skipped"` with a `reason`
    string. When `task_id` is given, the decision ALSO lands on that
    task's activity feed via the service layer with `actor=CONDUCTOR_NAME`
    (AP-376 invariant) — so a task-touching Conductor decision shows up
    next to every other actor's activity, not just in this audit table."""
    from backend.forge.repos import planning_turns as pt_repo
    decision = {"action": action, "task_id": task_id, "agent": agent, "reason": reason}
    with SessionLocal() as db:
        pt_repo.append_decision(db, turn_id, decision)
        if task_id:
            from backend.forge.repos import activities as activities_repo
            activities_repo.add_task_comment(
                db, project_id=project_id, task_id=task_id,
                detail=f"🧭 **Conductor** {action}: {reason}", actor=CONDUCTOR_NAME)
        db.commit()


def get_recent_planning_turns(limit: int = 20) -> list[dict]:
    """Recent PlanningTurn records, newest first — powers the Conductor
    feed (workflow-editor spec §9: activity-feed rows deep-link to tasks)."""
    from backend.forge.repos import planning_turns as pt_repo
    with SessionLocal() as db:
        return pt_repo.list_recent(db, limit=limit)


def run_planning_turn() -> dict:
    """Dispatch one LLM planning turn PER conductor-managed project — each
    project's turn sees only that project's agents/tasks/backlog and gets
    its own `turn:{turn_id}` conversation scope (AP-4xx turn-scopes rework:
    the old single aggregate turn on `chat:default` mixed every project's
    facts into one unbounded-growth conversation). Skips (token-free) per
    project when there's nothing to plan for it.

    Every project with plannable work produces a durable `PlanningTurn`
    record (AP-401) — facts snapshot, model, duration, scope key — even
    when it skips. A dispatched turn's `decisions` list starts empty and
    fills in asynchronously as the Conductor's LLM turn actually assigns
    tasks (see `record_planning_decision`).

    Returns `{"projects": [...]}`, one result dict per managed project, or
    a top-level `{"skipped": ...}` when the Conductor itself can't run at
    all (disabled / not seeded / no runtime / nothing to manage).
    """
    global _LAST_PLAN
    if not _conductor_active():
        _LAST_PLAN = {"skipped": "conductor_disabled"}
        return _LAST_PLAN
    with SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == CONDUCTOR_NAME).first()
        if not prof:
            _LAST_PLAN = {"skipped": "no_conductor"}
            return _LAST_PLAN
        managed = _managed_projects(db)
        if not managed:
            _LAST_PLAN = {"skipped": "no_managed_projects"}
            return _LAST_PLAN
        if not prof.runtime_id:
            _LAST_PLAN = {"skipped": "no_runtime"}
            return _LAST_PLAN
        conductor_id = prof.id
        conductor_model = prof.model

    from backend.forge import services
    from backend.forge.repos import planning_turns as pt_repo
    results: list[dict] = []
    for project_id, project_name in managed:
        start = time.monotonic()
        facts = gather_planning_facts(project_id)
        if not facts["unassigned_tasks"] and not facts["backlog"]:
            _record_planning_turn(
                trigger="cron", status="skipped", facts=facts,
                duration_ms=int((time.monotonic() - start) * 1000),
                decisions=[{"action": "skipped", "task_id": None, "agent": None,
                           "reason": "nothing to plan — no unassigned tasks or backlog"}])
            results.append({"project_id": project_id, "skipped": "nothing to plan"})
            continue

        turn_id = _record_planning_turn(
            trigger="cron", status="dispatched", facts=facts, model=conductor_model,
            duration_ms=int((time.monotonic() - start) * 1000))
        scope_key = f"turn:{turn_id}"
        prompt = _compose_planning_prompt(facts)
        try:
            services.send_runtime_message(
                conductor_id, content=prompt, scope_key=scope_key)
            with SessionLocal() as scope_db:
                pt_repo.set_scope_key(scope_db, turn_id, scope_key)
                scope_db.commit()
            results.append({
                "project_id": project_id, "ok": True, "turn_id": turn_id,
                "scope_key": scope_key,
                "unassigned": len(facts["unassigned_tasks"]),
                "backlog": len(facts["backlog"]),
            })
            logger.info("Conductor planning turn dispatched project=%s "
                        "(%d unassigned, %d backlog).", project_id,
                        len(facts["unassigned_tasks"]), len(facts["backlog"]))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Planning turn dispatch failed project=%s: %s",
                             project_id, exc)
            with SessionLocal() as scope_db:
                pt_repo.update_status(scope_db, turn_id, "error")
                scope_db.commit()
            results.append({"project_id": project_id, "error": str(exc),
                            "turn_id": turn_id})

    _LAST_PLAN = {"at": datetime.now(timezone.utc).isoformat(), "projects": results}
    return _LAST_PLAN


# ── AP-232: Conductor progress watchdog ──────────────────────────────────
#
# Deterministic sweeps catch the failure classes we already know how to
# name (zombie runs, gate failures, hand-off misses — AP-119, AP-231,
# AP-208). The watchdog covers the residue: a task quietly stuck without
# a terminal-failed signal, an agent looping without output, work parked
# in review for hours. Same code+LLM split as the planning turn — facts
# are gathered token-free here; the judgment is one LLM call on the
# planning cadence (templates/conductor/progress_check.md).

# A task in `in_progress` or `review` whose latest run has shown no
# activity for this long is "stalled" — surface it to the Conductor for
# judgment (re-dispatch / reassign / escalate). The threshold deliberately
# floors well above the reconciler's stale-run window
# (backend.forge.reconciler.STALE_RUN_THRESHOLD_S, 120s) so we never flag
# a run that the reconciler is about to mark FAILED on its own — the
# watchdog is for the cases reconciliation can't classify.
STALLED_NO_ACTIVITY_MINUTES = 30

# Most recent progress-check turn result — observability for /status.
_LAST_PROGRESS_CHECK: dict | None = None


def get_last_progress_check() -> dict | None:
    return _LAST_PROGRESS_CHECK


def _review_status_id(db) -> str | None:
    row = db.query(Status).filter(Status.name == "review").first()
    return row.id if row else None


def _aware_utc(ts: datetime) -> datetime:
    """SQLite stores `DateTime(timezone=True)` as naive — normalise to
    tz-aware UTC so cross-backend comparisons never crash."""
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


def _run_last_activity(run: Run) -> datetime:
    """The latest timestamp on a run that proves "something happened."

    Falls through last_heartbeat_at → finished_at → started_at → created_at
    so a quiet-but-not-yet-finished run, a completed run, and a freshly-
    dispatched-but-never-started run all yield a real timestamp.
    """
    for ts in (run.last_heartbeat_at, run.finished_at, run.started_at,
               run.created_at):
        if ts is not None:
            return _aware_utc(ts)
    # Safe sentinel — a run with no timestamps at all is degenerate, but the
    # watchdog must not crash; treat it as "just appeared".
    return datetime.now(timezone.utc)


def gather_progress_facts(
        project_id: str | None = None, *,
        stale_minutes: int = STALLED_NO_ACTIVITY_MINUTES) -> dict:
    """Token-free snapshot of tasks the deterministic layers couldn't move.

    Looks at every task in `in_progress` or `review` across projects with
    a conductor-enabled agent (so we don't scan unrelated workspaces) —
    or, when `project_id` is given, scoped to that ONE project only (the
    per-project progress-check turn, AP-4xx turn-scopes rework) — and
    flags it as `stalled` when either:

      1. The latest run terminated with outcome=FAILED — last attempt
         died; auto-recovery never picked it up.
      2. The latest run has shown no activity for `stale_minutes` —
         either non-terminal-but-quiet (likely hung) or terminal-but-
         the-workflow-driver-never-advanced-the-task.

    Each item carries enough context for the Conductor's LLM judgment
    (assignee, priority, stalled_reason, minutes_idle, last error / outcome)
    without re-reading the whole run history. Tasks with no runs at all are
    deliberately NOT included — `in_progress`-without-a-run is the planning
    turn's responsibility, not progress monitoring.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    stalled: list[dict] = []
    with SessionLocal() as db:
        ip_id = _in_progress_status_id(db)
        review_id = _review_status_id(db)
        active_status_ids = [s for s in (ip_id, review_id) if s]
        if not active_status_ids:
            return {"stalled_tasks": [], "threshold_minutes": stale_minutes}

        # Limit to projects the Conductor manages (same scoping as planning).
        managed_project_ids = {
            p.default_project_id
            for p in db.query(Profile)
                       .filter(Profile.conductor_enabled == True)  # noqa: E712
                       .filter(Profile.default_project_id.isnot(None))
                       .all()}
        if project_id is not None:
            managed_project_ids &= {project_id}
        if not managed_project_ids:
            return {"stalled_tasks": [], "threshold_minutes": stale_minutes}

        rows = (db.query(Task)
                  .filter(Task.project_id.in_(managed_project_ids),
                          Task.status_id.in_(active_status_ids))
                  .order_by(Task.created_at.asc())
                  .limit(FACTS_SCAN_LIMIT)
                  .all())

        # Status id → name (one query, lookup map — avoids N+1).
        status_map = {s.id: s.name
                      for s in db.query(Status)
                                 .filter(Status.id.in_(active_status_ids))
                                 .all()}

        # Latest run per task — one query for all rows (was one Run query
        # per task in the loop). Ordering by (task_id, created_at desc)
        # means the first row seen for a task_id is its latest run.
        task_ids = [t.id for t in rows]
        latest_run_by_task: dict[str, Run] = {}
        if task_ids:
            for r in (db.query(Run)
                        .filter(Run.task_id.in_(task_ids))
                        .order_by(Run.task_id, Run.created_at.desc())
                        .all()):
                latest_run_by_task.setdefault(r.task_id, r)

        now = datetime.now(timezone.utc)
        for t in rows:
            run = latest_run_by_task.get(t.id)
            if run is None:
                continue   # task without a run is planning's concern
            last_activity = _run_last_activity(run)
            outcome = run.outcome.value if run.outcome and hasattr(
                run.outcome, "value") else (run.outcome or None)
            run_status = run.status.value if hasattr(
                run.status, "value") else str(run.status or "")
            failed = (outcome == "failed"
                      or run_status in ("FAILED", "CANCELLED"))
            quiet = last_activity < cutoff
            if not failed and not quiet:
                continue
            if failed and quiet:
                reason = "last_run_failed_and_idle"
            elif failed:
                reason = "last_run_failed"
            else:
                reason = "no_activity"
            stalled.append({
                "task_id": t.id,
                "key": t.key,
                "title": t.title,
                "project_id": t.project_id,
                "status": status_map.get(t.status_id, "?"),
                "priority": (t.priority.value if hasattr(t.priority, "value")
                             else (t.priority or "medium")),
                "assignee": t.assignee or "",
                "stalled_reason": reason,
                "minutes_idle": int((now - last_activity).total_seconds() // 60),
                "last_run": {
                    "id": run.id,
                    "status": run_status,
                    "outcome": outcome,
                    "error": (run.error or "")[:300],
                    "summary": (run.summary or "")[:300],
                },
            })
    # Newest stalls first — the Conductor sees the freshest hangs.
    stalled.sort(key=lambda r: r["minutes_idle"])
    return {"stalled_tasks": stalled, "threshold_minutes": stale_minutes}


def _compose_progress_check_prompt(facts: dict) -> str:
    """Fill the progress-check template (config) with the stalled-task list.

    Same pattern as the planning prompt: code serialises facts into rows,
    prose lives in templates/conductor/progress_check.md. Fenced (data, not
    instructions — section C) and prefixed with the injection guard.
    """
    lines = []
    for s in facts["stalled_tasks"]:
        last = s["last_run"]
        tail = ""
        if last.get("error"):
            tail = f"\n    last error: {last['error']}"
        elif last.get("summary"):
            tail = f"\n    last summary: {last['summary']}"
        lines.append(
            f"- task_id={s['task_id']} [{s.get('key') or '?'}] "
            f"({s.get('priority') or 'medium'}, {s['status']}) — "
            f"{s['title']} — assignee={s['assignee'] or '(unassigned)'} "
            f"— stalled_reason={s['stalled_reason']} "
            f"— idle={s['minutes_idle']}m"
            + tail)
    stalled = "\n".join(lines) or "- (none)"
    project_name = facts.get("project_name") or facts.get("project_id") or ""
    body = (_load_prompt("conductor/progress_check.md")
            .replace("{{STALLED}}", _fenced(stalled))
            .replace("{{THRESHOLD}}", str(facts["threshold_minutes"])))
    return _compose_turn_guard(project_name) + "\n\n" + body


def run_progress_check_turn() -> dict:
    """Dispatch one LLM judgment turn PER conductor-managed project, over
    that project's stalled list only (AP-4xx turn-scopes rework — mirrors
    `run_planning_turn`'s per-project split). Skips (token-free) per
    project when nothing is stalled there.

    Every project produces a durable `PlanningTurn` record
    (trigger="progress_check") with its own `turn:{turn_id}` scope — never
    `chat:default`. Same cadence as planning (`plan_interval_minutes`), so
    a single Conductor wake-up handles both judgments per project.
    """
    global _LAST_PROGRESS_CHECK
    if not _conductor_active():
        _LAST_PROGRESS_CHECK = {"skipped": "conductor_disabled"}
        return _LAST_PROGRESS_CHECK
    with SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == CONDUCTOR_NAME).first()
        if not prof:
            _LAST_PROGRESS_CHECK = {"skipped": "no_conductor"}
            return _LAST_PROGRESS_CHECK
        managed = _managed_projects(db)
        if not managed:
            _LAST_PROGRESS_CHECK = {"skipped": "no_managed_projects"}
            return _LAST_PROGRESS_CHECK
        if not prof.runtime_id:
            _LAST_PROGRESS_CHECK = {"skipped": "no_runtime"}
            return _LAST_PROGRESS_CHECK
        conductor_id = prof.id

    from backend.forge import services
    from backend.forge.repos import planning_turns as pt_repo
    results: list[dict] = []
    for project_id, project_name in managed:
        facts = gather_progress_facts(project_id)
        if not facts["stalled_tasks"]:
            results.append({"project_id": project_id, "skipped": "nothing_stalled"})
            continue
        facts_snapshot = {**facts, "project_id": project_id,
                          "project_name": project_name}
        turn_id = _record_planning_turn(
            trigger="progress_check", status="dispatched", facts=facts_snapshot)
        scope_key = f"turn:{turn_id}"
        prompt = _compose_progress_check_prompt(facts_snapshot)
        try:
            services.send_runtime_message(
                conductor_id, content=prompt, scope_key=scope_key)
            with SessionLocal() as scope_db:
                pt_repo.set_scope_key(scope_db, turn_id, scope_key)
                scope_db.commit()
            results.append({
                "project_id": project_id, "ok": True, "turn_id": turn_id,
                "scope_key": scope_key, "stalled": len(facts["stalled_tasks"]),
                "threshold_minutes": facts["threshold_minutes"],
            })
            logger.info("Conductor progress-check dispatched project=%s "
                        "(%d stalled).", project_id, len(facts["stalled_tasks"]))
        except Exception as exc:  # noqa: BLE001 — never break the caller
            logger.exception("Progress-check dispatch failed project=%s: %s",
                             project_id, exc)
            with SessionLocal() as scope_db:
                pt_repo.update_status(scope_db, turn_id, "error")
                scope_db.commit()
            results.append({"project_id": project_id, "error": str(exc),
                            "turn_id": turn_id})

    _LAST_PROGRESS_CHECK = {"at": datetime.now(timezone.utc).isoformat(),
                            "projects": results}
    return _LAST_PROGRESS_CHECK


# ── Sprint review — the loop's retro (B) ──────────────────────────────────
#
# Neither the queue tick nor the planning/progress turns ever look BACK at
# what shipped, failed, or bounced — so a systemic issue (a gate that keeps
# bouncing, an agent stuck on the same class of bug) never turns into a
# corrective backlog task on its own. The sprint review closes that loop:
# once a day, per project, it reviews the last 24h and (via its MCP tool
# calls) files corrective backlog tasks and publishes the review itself as
# a `done` task on the board so a non-technical owner reads it there.

_LAST_SPRINT_REVIEW: dict | None = None


def get_last_sprint_review() -> dict | None:
    return _LAST_SPRINT_REVIEW


def gather_sprint_review_facts(project_id: str) -> dict:
    """Token-free 24h digest for ONE project's sprint review: outcome
    counts + cost (from `generate_digest`, already project-scoped), the
    bounce/escalation comment count (systemic-issue signal), and the
    done/failed task lists for the review prose.

    Gate-evaluation outcomes are deliberately NOT included: `GateEvaluation`
    has no timestamp column to window by, so a cheap 24h count isn't
    available without a schema change — out of scope for this pass (see
    docs/conductor-turns.md deviations).
    """
    from backend.forge.digest import generate_digest
    from datetime import datetime as _dt

    with SessionLocal() as db:
        project = db.get(Project, project_id)
        project_name = project.name if project else project_id

    d = generate_digest(project_id=project_id, since="24h")
    if d.get("error"):
        return {"project_id": project_id, "project_name": project_name,
                "counts": {}, "stats": {}, "done": [], "failed": [],
                "bounce_escalation_count": 0}

    since_ts = _dt.fromisoformat(d["window"]["since"])
    with SessionLocal() as db:
        from backend.forge.repos import activities as activities_repo
        bounce_escalation_count = activities_repo.count_bounce_escalation_comments(
            db, project_id=project_id, since=since_ts)

    return {
        "project_id": project_id, "project_name": project_name,
        "counts": d["counts"], "stats": d["stats"],
        "done": [{"key": c["task_key"], "title": c["task_title"]}
                for c in d["done"]],
        "failed": [{"key": c["task_key"], "title": c["task_title"],
                    "summary": c["summary"]} for c in d["failed"]],
        "bounce_escalation_count": bounce_escalation_count,
    }


def _compose_sprint_review_prompt(facts: dict) -> str:
    """Fill the sprint-review template (config) with the gathered facts.

    Code only serialises facts into rows; all instruction prose lives in
    templates/conductor/sprint_review.md (prompts-are-config). Task lists
    are fenced (data, not instructions — section C).
    """
    c = facts.get("counts") or {}
    stats = facts.get("stats") or {}
    project_name = facts.get("project_name") or facts.get("project_id") or ""
    done = "\n".join(
        f"- [{t.get('key') or '?'}] {t.get('title')}" for t in facts.get("done") or []
    ) or "- (none)"
    failed = "\n".join(
        f"- [{t.get('key') or '?'}] {t.get('title')}"
        + (f" — {t['summary']}" if t.get("summary") else "")
        for t in facts.get("failed") or []
    ) or "- (none)"
    body = (_load_prompt("conductor/sprint_review.md")
            .replace("{{PROJECT}}", project_name)
            .replace("{{DONE_COUNT}}", str(c.get("done", 0)))
            .replace("{{FAILED_COUNT}}", str(c.get("failed", 0)))
            .replace("{{BLOCKED_COUNT}}", str(c.get("blocked", 0)))
            .replace("{{NEEDS_INPUT_COUNT}}", str(c.get("needs_input", 0)))
            .replace("{{IN_FLIGHT_COUNT}}", str(c.get("in_flight", 0)))
            .replace("{{COST_USD}}", str(stats.get("cost_usd", 0)))
            .replace("{{BOUNCE_ESCALATION_COUNT}}",
                     str(facts.get("bounce_escalation_count", 0)))
            .replace("{{DONE_TASKS}}", _fenced(done))
            .replace("{{FAILED_TASKS}}", _fenced(failed)))
    return _compose_turn_guard(project_name) + "\n\n" + body


def run_sprint_review_turn() -> dict:
    """Dispatch one LLM sprint-review (retro) turn PER conductor-managed
    project, daily. Skips (token-free) per project when the 24h digest is
    empty (no counts, no bounce/escalation activity — nothing to review).

    Every dispatched project produces a durable `PlanningTurn` record
    (trigger="sprint_review") with its own `turn:{turn_id}` scope.
    """
    global _LAST_SPRINT_REVIEW
    if not _conductor_active():
        _LAST_SPRINT_REVIEW = {"skipped": "conductor_disabled"}
        return _LAST_SPRINT_REVIEW
    with SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == CONDUCTOR_NAME).first()
        if not prof:
            _LAST_SPRINT_REVIEW = {"skipped": "no_conductor"}
            return _LAST_SPRINT_REVIEW
        managed = _managed_projects(db)
        if not managed:
            _LAST_SPRINT_REVIEW = {"skipped": "no_managed_projects"}
            return _LAST_SPRINT_REVIEW
        if not prof.runtime_id:
            _LAST_SPRINT_REVIEW = {"skipped": "no_runtime"}
            return _LAST_SPRINT_REVIEW
        conductor_id = prof.id
        conductor_model = prof.model

    from backend.forge import services
    from backend.forge.repos import planning_turns as pt_repo
    results: list[dict] = []
    for project_id, project_name in managed:
        start = time.monotonic()
        facts = gather_sprint_review_facts(project_id)
        counts = facts.get("counts") or {}
        if not any(counts.values()) and not facts.get("bounce_escalation_count"):
            _record_planning_turn(
                trigger="sprint_review", status="skipped", facts=facts,
                duration_ms=int((time.monotonic() - start) * 1000),
                decisions=[{"action": "skipped", "task_id": None, "agent": None,
                           "reason": "empty 24h digest — nothing to review"}])
            results.append({"project_id": project_id, "skipped": "empty_digest"})
            continue

        turn_id = _record_planning_turn(
            trigger="sprint_review", status="dispatched", facts=facts,
            model=conductor_model,
            duration_ms=int((time.monotonic() - start) * 1000))
        scope_key = f"turn:{turn_id}"
        prompt = _compose_sprint_review_prompt(facts)
        try:
            services.send_runtime_message(
                conductor_id, content=prompt, scope_key=scope_key)
            with SessionLocal() as scope_db:
                pt_repo.set_scope_key(scope_db, turn_id, scope_key)
                scope_db.commit()
            results.append({"project_id": project_id, "ok": True,
                            "turn_id": turn_id, "scope_key": scope_key})
            logger.info("Conductor sprint review dispatched project=%s.", project_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Sprint review dispatch failed project=%s: %s",
                             project_id, exc)
            with SessionLocal() as scope_db:
                pt_repo.update_status(scope_db, turn_id, "error")
                scope_db.commit()
            results.append({"project_id": project_id, "error": str(exc),
                            "turn_id": turn_id})

    _LAST_SPRINT_REVIEW = {"at": datetime.now(timezone.utc).isoformat(),
                           "projects": results}
    return _LAST_SPRINT_REVIEW
