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

A deterministic queue tick dispatches assigned todo work to free agents
for free (no tokens, not you). You are invoked for the three jobs that
need judgment:

QUEUE PLANNING: you are given the unassigned todo tasks and the
available agents. Assign each task to the best-fit agent in the same
project (skill fit + load balance) by calling mcp__agentira__update_task
with the agent's exact name as `assignee`. Only touch the tasks you're
given. Be terse — just make the update_task calls.

DAILY REPORT: compile the digest, review progress, surface blockers and
stuck runs, recommend priorities. Output it as a self-contained HTML
fragment exactly as the prompt specifies — the dashboard renders it as a
formatted executive report.

PROJECT KICKOFF: when assigned a "Plan this project" task in a new
project, read the project description and any attachments (list_attachments,
download_attachment). Pick the tools/tech stack with a brief justification
for each choice. Register a one-page plan covering architecture, milestones,
and risks as a real artifact via
mcp__agentira__register_run_artifact(kind="report", label="Project plan").
Break the work into 3–8 concrete child tasks via mcp__agentira__create_task,
each with a clear DoD. Then mcp__agentira__finish_run(outcome="succeeded").
If the brief is too vague to plan from, finish_run(outcome="needs_input")
with a specific question — a follow-up comment on this task will resume
you (you'll see it in the chat).

Rules of economy — you cost tokens, the scripts do not:
- The facts you need are already in the prompt. Don't re-derive them.
- Spend reasoning only on judgment: best-fit assignment, what matters
  most, whether a run is stuck.
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

        # System singleton — always sync the prompt to the canonical
        # source. Users who want a custom orchestrator persona should
        # create their own agent rather than mutating this one (otherwise
        # new "modes" like the kickoff added for AP-150 never reach
        # existing workspaces).
        if prof.system_prompt != CONDUCTOR_SYSTEM_PROMPT:
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
    """Render the gathered facts into the Conductor's report prompt."""
    import json as _json
    lines = ["DAILY REPORT.", ""]
    projects = facts.get("projects") or []
    if projects:
        lines.append("## Per-project activity (last 24h)")
        for p in projects:
            c = p["counts"]
            lines.append(
                f"- {p['project']}: {c.get('done', 0)} done, "
                f"{c.get('blocked', 0)} blocked, "
                f"{c.get('needs_input', 0)} needs-input, "
                f"{c.get('failed', 0)} failed, "
                f"{c.get('in_flight', 0)} in-flight "
                f"(${p['stats'].get('cost_usd', 0)})"
            )
    else:
        lines.append("## Per-project activity (last 24h)\n- No run activity.")
    agents = (facts.get("survey") or {}).get("agents") or []
    lines.append("")
    lines.append("## Worker agents")
    if agents:
        for a in agents:
            nxt = a.get("next_task")
            lines.append(
                f"- {a['name']}: {a['in_flight']}/{a['capacity']} in-flight; "
                f"next: {nxt['title'] if nxt else 'nothing queued'}"
            )
    else:
        lines.append("- No conductor-enabled worker agents.")
    lines.append("")
    lines.append(
        "Write the daily report for the workspace owner as an executive "
        "briefing. Output a SINGLE self-contained HTML fragment and nothing "
        "else — no preamble, no markdown, no code fences, no <html>/<head>/"
        "<body> wrapper. Begin your reply with `<section` and end it with "
        "`</section>`.\n"
        "\n"
        "Structure the report exactly like this:\n"
        "  <section class=\"daily-report\"> wrapping everything.\n"
        "  1. An <h1> title and a one-line <p class=\"subtitle\"> with the date.\n"
        "  2. A <div class=\"kpis\"> row of stat cards — one <div class=\"kpi\"> "
        "per headline metric (tasks done, blocked, failed, in-flight, total "
        "cost). Each card: <div class=\"kpi-value\">N</div>"
        "<div class=\"kpi-label\">…</div>.\n"
        "  3. <h2>Wins</h2> — what got done overnight, as a <ul>.\n"
        "  4. <h2>Blocked &amp; needs input</h2> — each item and what unblocks "
        "it.\n"
        "  5. <h2>Failing / needs attention</h2>.\n"
        "  6. <h2>Today's priorities</h2> — an ordered <ol> of 2-3 items.\n"
        "\n"
        "Use only these tags: section, div, h1, h2, p, ul, ol, li, strong, "
        "em, span, table, thead, tbody, tr, th, td. Use the class names above "
        "so the dashboard can style it. Do NOT add inline styles or scripts. "
        "Lead with the most important thing; be concise and factual."
    )
    return "\n".join(lines)


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


def gather_planning_facts() -> dict:
    """Token-free snapshot for the planning turn: the conductor-enabled
    agents and the UNASSIGNED, un-run todo tasks in their projects."""
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
                    "project_id": t.project_id, "priority": t.priority,
                })
    return {"agents": agents, "unassigned_tasks": tasks}


def _compose_planning_prompt(facts: dict) -> str:
    lines = ["QUEUE PLANNING.", ""]
    lines.append("## Agents available for auto-dispatch")
    for a in facts["agents"]:
        lines.append(
            f"- {a['name']} — project {a['project_id']} — "
            f"{a['in_flight']}/{a['capacity']} in flight"
        )
    lines.append("")
    lines.append("## Unassigned todo tasks (need an owner)")
    for t in facts["unassigned_tasks"]:
        lines.append(
            f"- task_id={t['id']} [{t.get('key') or '?'}] "
            f"({t.get('priority') or 'medium'}) — {t['title']} "
            f"— project {t['project_id']}"
        )
    lines.append("")
    lines.append(
        "Assign each unassigned task to the best-fit agent IN THE SAME "
        "PROJECT. Balance load — don't pile everything on one agent; "
        "weigh in_flight vs capacity. For each task you assign, call "
        "mcp__agentira__update_task with task_id and assignee set to the "
        "agent's exact name (optionally also set priority). Only touch the "
        "tasks listed above — do not reassign anything else. If a task has "
        "no suitable agent in its project, leave it. Be terse; just make "
        "the update_task calls."
    )
    return "\n".join(lines)


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
