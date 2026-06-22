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
from pathlib import Path

from sqlalchemy import select

from backend.db import SessionLocal
from backend.models import Profile, Project, Task, Status, Role
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
                    "plan_interval_minutes": 10}
        # Clamp the tick to a sane floor — a sub-10s tick would hammer the DB.
        tick = max(10, int(prof.conductor_tick_seconds or TICK_INTERVAL_S))
        # Planning turn costs tokens — floor it at 1 min.
        plan = max(1, int(prof.conductor_plan_interval_minutes or 10))
        return {"active": bool(prof.conductor_active),
                "tick_seconds": tick,
                "report_time": prof.conductor_report_time or "09:00",
                "report_enabled": bool(prof.conductor_report_enabled),
                "plan_interval_minutes": plan}


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


# Lower rank = dispatched first. Unknown/missing priority sorts as medium.
_PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def pick_next_unblocked(*, project_id: str, agent_id: str, db=None) -> "Task | None":
    """Return the next FRESH todo task ASSIGNED to `agent_id` in `project_id`.

    Eligible: status == 'todo', assignee == this agent (exact name), AND the
    task has NO run yet. The no-run rule is the runaway guard — a task is
    auto-picked at most once; after that it has a run and is permanently
    ineligible for auto-pickup.

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
        # Tasks that already have a run — never auto-pick these again.
        tasks_with_runs = select(Run.task_id).where(Run.task_id.isnot(None))
        rows = (db.query(Task)
                  .filter(Task.project_id == project_id,
                          Task.status_id == todo_id,
                          Task.id.notin_(tasks_with_runs),
                          Task.assignee == agent.name)
                  .order_by(Task.created_at.asc())
                  .all())
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
    if not _conductor_active():
        # Keep the same shape as a normal tick — `skipped` is always the
        # list of skipped-agent records; `disabled` is the off marker.
        _LAST_TICK = {"disabled": True,
                      "dispatched": [], "skipped": [], "reconciled": []}
        return _LAST_TICK
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
            in_progress_id = _in_progress_status_id(db)

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
    try:
        from backend.forge import services
        services.send_runtime_message(
            conductor_id, content=prompt, scope_key="chat:default")
        _LAST_REPORT = {"ok": True, "at": datetime.now(timezone.utc).isoformat(),
                        "projects": len(facts.get("projects") or [])}
        logger.info("Conductor daily report dispatched.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Daily report dispatch failed: %s", exc)
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


def gather_planning_facts() -> dict:
    """Token-free snapshot for the planning turn: the conductor-enabled
    agents (with specialty/model, so the planner can skill-match) and the
    UNASSIGNED, un-run todo tasks (with description/priority) in their
    projects."""
    with SessionLocal() as db:
        todo_id = _todo_status_id(db)
        profiles = (db.query(Profile)
                      .filter(Profile.conductor_enabled == True)  # noqa: E712
                      .filter(Profile.default_project_id.isnot(None))
                      .all())
        agents: list[dict] = []
        project_ids: set[str] = set()
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
            project_ids.add(prof.default_project_id)

        tasks: list[dict] = []
        if todo_id and project_ids:
            tasks_with_runs = select(Run.task_id).where(Run.task_id.isnot(None))
            rows = (db.query(Task)
                      .filter(Task.project_id.in_(project_ids),
                              Task.status_id == todo_id,
                              Task.id.notin_(tasks_with_runs),
                              (Task.assignee == "") | (Task.assignee.is_(None)))
                      .order_by(Task.created_at.asc())
                      .all())
            for t in rows:
                tasks.append({
                    "id": t.id, "key": t.key, "title": t.title,
                    "project_id": t.project_id,
                    "priority": t.priority.value if hasattr(t.priority, "value")
                                else (t.priority or "medium"),
                    "description": (t.description or "")[:300],
                })
    return {"agents": agents, "unassigned_tasks": tasks}


def _compose_planning_prompt(facts: dict) -> str:
    """Fill the planning-turn template (config) with the gathered facts.

    Code only serialises the facts into rows; all instruction prose lives
    in templates/conductor/planning_turn.md (prompts-are-config).
    """
    agents = "\n".join(
        f"- {a['name']} ({a.get('model') or 'model?'}) — project {a['project_id']} — "
        f"{a['in_flight']}/{a['capacity']} in flight"
        + (f"\n    specialty: {a['specialty']}" if a.get("specialty") else "")
        for a in facts["agents"]
    ) or "- (none)"
    tasks = "\n".join(
        f"- task_id={t['id']} [{t.get('key') or '?'}] "
        f"({t.get('priority') or 'medium'}) — {t['title']} "
        f"— project {t['project_id']}"
        + (f"\n    {t['description']}" if t.get("description") else "")
        for t in facts["unassigned_tasks"]
    ) or "- (none)"
    return (_load_prompt("conductor/planning_turn.md")
            .replace("{{AGENTS}}", agents)
            .replace("{{TASKS}}", tasks))


def run_planning_turn() -> dict:
    """Dispatch one LLM planning turn to the Conductor — it assigns the
    unassigned todo backlog to agents. Skips (token-free) when there is
    nothing to plan or the Conductor has no runtime."""
    global _LAST_PLAN
    if not _conductor_active():
        _LAST_PLAN = {"skipped": "conductor_disabled"}
        return _LAST_PLAN
    facts = gather_planning_facts()
    if not facts["unassigned_tasks"] or not facts["agents"]:
        _LAST_PLAN = {"skipped": "nothing to plan"}
        return _LAST_PLAN
    with SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == CONDUCTOR_NAME).first()
        if not prof:
            _LAST_PLAN = {"skipped": "no_conductor"}
            return _LAST_PLAN
        if not prof.runtime_id:
            _LAST_PLAN = {"skipped": "no_runtime"}
            return _LAST_PLAN
        conductor_id = prof.id

    prompt = _compose_planning_prompt(facts)
    try:
        from backend.forge import services
        services.send_runtime_message(
            conductor_id, content=prompt, scope_key="chat:default")
        _LAST_PLAN = {"ok": True, "at": datetime.now(timezone.utc).isoformat(),
                      "unassigned": len(facts["unassigned_tasks"]),
                      "agents": len(facts["agents"])}
        logger.info("Conductor planning turn dispatched (%d unassigned).",
                    len(facts["unassigned_tasks"]))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Planning turn dispatch failed: %s", exc)
        _LAST_PLAN = {"error": str(exc)}
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
# floors at the run-staleness reaper window (STALE_RUN_SILENCE_MINUTES=20)
# so we never flag a run that the reconciler is about to mark FAILED on
# its own — the watchdog is for the cases reconciliation can't classify.
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
        *, stale_minutes: int = STALLED_NO_ACTIVITY_MINUTES) -> dict:
    """Token-free snapshot of tasks the deterministic layers couldn't move.

    Looks at every task in `in_progress` or `review` across projects with
    a conductor-enabled agent (so we don't scan unrelated workspaces) and
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
        if not managed_project_ids:
            return {"stalled_tasks": [], "threshold_minutes": stale_minutes}

        rows = (db.query(Task)
                  .filter(Task.project_id.in_(managed_project_ids),
                          Task.status_id.in_(active_status_ids))
                  .all())

        # Status id → name (one query, lookup map — avoids N+1).
        status_map = {s.id: s.name
                      for s in db.query(Status)
                                 .filter(Status.id.in_(active_status_ids))
                                 .all()}

        now = datetime.now(timezone.utc)
        for t in rows:
            run = (db.query(Run)
                     .filter(Run.task_id == t.id)
                     .order_by(Run.created_at.desc())
                     .first())
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
    prose lives in templates/conductor/progress_check.md.
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
    return (_load_prompt("conductor/progress_check.md")
            .replace("{{STALLED}}", stalled)
            .replace("{{THRESHOLD}}", str(facts["threshold_minutes"])))


def run_progress_check_turn() -> dict:
    """Dispatch one LLM judgment turn to the Conductor over the stalled list.

    Skips (token-free) when there is nothing stalled or the Conductor has
    no runtime. Same shape and dispatch path as `run_planning_turn` — the
    progress check is meant to run on the same cadence (`plan_interval_minutes`)
    as planning, so a single Conductor wake-up handles both judgments.
    """
    global _LAST_PROGRESS_CHECK
    if not _conductor_active():
        _LAST_PROGRESS_CHECK = {"skipped": "conductor_disabled"}
        return _LAST_PROGRESS_CHECK
    facts = gather_progress_facts()
    if not facts["stalled_tasks"]:
        _LAST_PROGRESS_CHECK = {"skipped": "nothing_stalled"}
        return _LAST_PROGRESS_CHECK
    with SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == CONDUCTOR_NAME).first()
        if not prof:
            _LAST_PROGRESS_CHECK = {"skipped": "no_conductor"}
            return _LAST_PROGRESS_CHECK
        if not prof.runtime_id:
            _LAST_PROGRESS_CHECK = {"skipped": "no_runtime"}
            return _LAST_PROGRESS_CHECK
        conductor_id = prof.id

    prompt = _compose_progress_check_prompt(facts)
    try:
        from backend.forge import services
        services.send_runtime_message(
            conductor_id, content=prompt, scope_key="chat:default")
        _LAST_PROGRESS_CHECK = {
            "ok": True, "at": datetime.now(timezone.utc).isoformat(),
            "stalled": len(facts["stalled_tasks"]),
            "threshold_minutes": facts["threshold_minutes"]}
        logger.info("Conductor progress-check dispatched (%d stalled).",
                    len(facts["stalled_tasks"]))
    except Exception as exc:  # noqa: BLE001 — never break the caller
        logger.exception("Progress-check dispatch failed: %s", exc)
        _LAST_PROGRESS_CHECK = {"error": str(exc)}
    return _LAST_PROGRESS_CHECK
