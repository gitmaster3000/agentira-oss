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

The Conductor only ever auto-picks a **fresh** todo task — one that has
*no run yet*. The moment a task is dispatched it (a) gets a Run row and
(b) is moved to `in_progress`. Either property alone disqualifies it
from being picked again. A task whose run failed therefore stays in
`in_progress` with a failed run for a human/Reviewer to judge — the
Conductor will NOT keep re-dispatching it. This is what stops the
"schedules runs indefinitely" loop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.db import SessionLocal
from backend.models import Profile, Task, Status, Role
from backend.forge.models import Agent, Run, RunStatus, AgentMessage, ForgeRuntime

logger = logging.getLogger("agentira.forge.conductor")

# Tick cadence (seconds) — each tick is one Conductor action.
TICK_INTERVAL_S = 60

# AP-119: a RUNNING/PENDING run that has shown no activity for this
# long is a zombie — its daemon-side process died without a
# trigger-complete (daemon crash, WS drop, OOM). A healthy run streams
# events continuously, so prolonged silence is a reliable staleness
# signal. The reconciler marks such runs FAILED so they stop showing
# as "running" forever and can't be stopped.
STALE_RUN_SILENCE_MINUTES = 20

# Identity of the Conductor agent.
CONDUCTOR_NAME = "Conductor"

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
# gather facts and act for free; the LLM is spent only on judgment.
CONDUCTOR_SYSTEM_PROMPT = """\
You are the Conductor — the orchestrator for this Agentira workspace.
Your job: keep task queues moving and runs healthy across every project.

You run in two modes:

QUEUE TICK (frequent, terse): survey the workspace, dispatch ready todo
work to free agents, flag stuck runs. If nothing needs doing, say so in
one line and stop — do not pad.

DAILY REPORT: compile the digest, review sprint progress, rebalance
assignments, surface blockers.

Rules of economy — you cost tokens, your scripts do not:
- ALWAYS call your tools (survey_workspace, find_free_agents, next_tasks,
  generate_report) to get facts. Never re-derive what a script returns.
- Spend reasoning only on judgment: which task matters most, whether a
  run is stuck, how to plan the sprint.
- Be terse. No preamble, no recap."""


def get_or_create_conductor() -> dict:
    """Return the Conductor agent, seeding it once if absent.

    The Conductor is a real LLM Agent — it shows in the agent list and is
    configured (model, runtime, prompt) like any other agent. Its
    intelligence is split: deterministic scripts (this module, exposed as
    MCP tools) gather facts and act token-free; the LLM is spent only on
    judgment — prioritisation, sprint planning, run monitoring.
    """
    import secrets
    with SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == CONDUCTOR_NAME).first()
        if prof is None:
            role = db.query(Role).filter(Role.name == "bot").first()
            if role is None:
                return {"error": "bot role missing"}
            prof = Profile(
                name=CONDUCTOR_NAME, display_name="Conductor",
                password_hash="", avatar_url="", webhook_url="",
                role_id=role.id, api_key=secrets.token_hex(32),
            )
            db.add(prof)
            db.commit()
            db.refresh(prof)
            logger.info("Seeded Conductor profile %s", prof.id)

        # Bind a Claude runtime if one is registered, so the Conductor can
        # actually take an LLM turn. If none yet, leave it null — the
        # agent still exists and gets a runtime when a daemon registers.
        claude_rt = (db.query(ForgeRuntime)
                       .filter(ForgeRuntime.provider == "claude")
                       .first())
        rt_id = claude_rt.id if claude_rt else None

        if not prof.system_prompt:
            prof.system_prompt = CONDUCTOR_SYSTEM_PROMPT
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

    `tick_seconds` drives the queue-tick interval; `report_time` /
    `report_enabled` drive the daily report. Falls back to module
    defaults if the Conductor profile isn't seeded yet.
    """
    with SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == CONDUCTOR_NAME).first()
        if not prof:
            return {"tick_seconds": TICK_INTERVAL_S,
                    "report_time": "09:00", "report_enabled": True}
        # Clamp the tick to a sane floor — a sub-10s tick would hammer the DB.
        tick = max(10, int(prof.conductor_tick_seconds or TICK_INTERVAL_S))
        return {"tick_seconds": tick,
                "report_time": prof.conductor_report_time or "09:00",
                "report_enabled": bool(prof.conductor_report_enabled)}


# ── Picker ───────────────────────────────────────────────────────────────

def _todo_status_id(db) -> str | None:
    row = db.query(Status).filter(Status.name == "todo").first()
    return row.id if row else None


def _in_progress_status_id(db) -> str | None:
    row = db.query(Status).filter(Status.name == "in_progress").first()
    return row.id if row else None


def pick_next_unblocked(*, project_id: str, agent_id: str, db=None) -> "Task | None":
    """Return the next FRESH todo task for `agent_id` in `project_id`.

    Eligible: status == 'todo', assignee is this agent or unassigned,
    AND the task has NO run yet. The no-run rule is the runaway guard —
    a task is auto-picked at most once; after that it has a run and is
    permanently ineligible for auto-pickup.

    FIFO by created_at. Caller owns the session if one is passed.
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
        # Tasks that already have a run — never auto-pick these again.
        tasks_with_runs = select(Run.task_id).where(Run.task_id.isnot(None))
        q = (db.query(Task)
               .filter(Task.project_id == project_id,
                       Task.status_id == todo_id,
                       Task.id.notin_(tasks_with_runs))
               .filter((Task.assignee == agent.name) | (Task.assignee == "")
                       | (Task.assignee.is_(None)))
               .order_by(Task.created_at.asc()))
        return q.first()
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
            })
    return {"agents": agents_view}


def reconcile_stale_runs() -> list[dict]:
    """AP-119: fail runs stuck RUNNING/PENDING with no recent activity.

    A run whose daemon-side process died without posting a
    trigger-complete (daemon crash, WS drop, OOM) stays RUNNING forever
    — it shows as "running" and the user can't stop it. We detect these
    by silence: a healthy run streams events continuously, so a run
    with no message newer than STALE_RUN_SILENCE_MINUTES is a zombie.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=STALE_RUN_SILENCE_MINUTES)
    reconciled: list[dict] = []
    with SessionLocal() as db:
        live = (db.query(Run)
                  .filter(Run.status.in_([RunStatus.RUNNING,
                                          RunStatus.PENDING]))
                  .all())
        for run in live:
            last_msg = (db.query(AgentMessage.created_at)
                          .filter(AgentMessage.run_id == run.id)
                          .order_by(AgentMessage.created_at.desc())
                          .first())
            last_activity = (last_msg[0] if last_msg
                             else (run.started_at or run.created_at))
            if last_activity is None:
                continue
            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)
            if last_activity < cutoff:
                run.status = RunStatus.FAILED
                run.error = (f"Stale — no activity for over "
                             f"{STALE_RUN_SILENCE_MINUTES} min; the daemon "
                             f"likely lost this run.")
                run.finished_at = datetime.now(timezone.utc)
                reconciled.append({"run": run.id, "agent": run.agent_id})
        if reconciled:
            db.commit()
            logger.warning("Reconciled %d stale run(s): %s",
                           len(reconciled), [r["run"] for r in reconciled])
    return reconciled


def run_tick() -> dict:
    """One Conductor action — workspace-wide.

    First reconciles zombie runs (AP-119), then for each conductor-
    enabled worker agent below its concurrency cap, picks its next FRESH
    todo task, dispatches it, and moves the task to in_progress so it is
    claimed exactly once. Per-agent failures are logged and skipped —
    one bad row must not stall the fleet.
    """
    global _LAST_TICK
    dispatched: list[dict] = []
    skipped: list[dict] = []

    # Run monitoring: clear zombies before dispatching new work.
    try:
        stale = reconcile_stale_runs()
    except Exception as exc:  # noqa: BLE001
        logger.warning("reconcile_stale_runs failed: %s", exc)
        stale = []

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
                dispatched.append({
                    "agent": agent.id, "task": task.id,
                    "run_id": result.get("run_id") if isinstance(result, dict) else None,
                })
                logger.info("Conductor dispatched agent=%s task=%s", agent.id, task.id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Conductor tick failed for agent=%s: %s", agent.id, exc)
                skipped.append({"agent": agent.id, "reason": "exception", "error": str(exc)})

    _LAST_TICK = {"dispatched": dispatched, "skipped": skipped,
                  "reconciled": stale}
    return _LAST_TICK
