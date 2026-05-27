"""Forge API router — mounted under /api/forge."""

from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket

from pydantic import BaseModel, Field

from backend.forge import services

router = APIRouter(prefix="/api/forge", tags=["forge"])

# Daemon-facing endpoints — no user JWT required. Daemons identify via
# persistent daemon_id; this is mounted separately without the global auth
# dependency so the host CLI can register/heartbeat without a user token.
daemon_router = APIRouter(prefix="/api/forge", tags=["forge-daemon"])


# ── Schemas ──────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str
    # runtime_id REQUIRED — Forge agents are dispatchable identities. For
    # API-key-only identities use Settings → Service Accounts instead.
    runtime_id: str
    profile_id: Optional[str] = None
    executor_type: str = "http"
    model: str = ""
    webhook_url: str = ""
    config_json: Optional[str] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    profile_id: Optional[str] = None
    executor_type: Optional[str] = None
    model: Optional[str] = None
    status: Optional[str] = None
    webhook_url: Optional[str] = None
    config_json: Optional[str] = None
    system_prompt: Optional[str] = None
    personality: Optional[str] = None
    runtime_type: Optional[str] = None
    runtime_url: Optional[str] = None
    runtime_gateway_token: Optional[str] = None
    runtime_hooks_token: Optional[str] = None
    runtime_agent_name: Optional[str] = None
    runtime_id: Optional[str] = None
    default_project_id: Optional[str] = None
    schedule_cron: Optional[str] = None
    mcp_servers: Optional[list[str]] = None
    mcp_disabled: Optional[list[str]] = None
    mcp_strict: Optional[bool] = None
    mcp_config_override: Optional[str] = None
    home_path: Optional[str] = None
    # AP-80 Conductor opt-in
    conductor_enabled: Optional[bool] = None
    max_concurrent_runs: Optional[int] = None
    # Conductor cadence config (Conductor agent only).
    conductor_tick_seconds: Optional[int] = None
    conductor_report_time: Optional[str] = None
    conductor_report_enabled: Optional[bool] = None
    conductor_plan_interval_minutes: Optional[int] = None
    conductor_active: Optional[bool] = None


class HeartbeatRequest(BaseModel):
    status: str = "online"


class RunCreate(BaseModel):
    agent_id: str
    task_id: Optional[str] = None
    project_id: Optional[str] = None
    trigger_event: str = ""
    model_used: str = ""


class RunComplete(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None


class DaemonTriggerEvents(BaseModel):
    daemon_id: str
    trace_id: str
    run_id: Optional[str] = None
    events: list


class DaemonTriggerComplete(BaseModel):
    daemon_id: str
    trace_id: str
    run_id: Optional[str] = None
    success: bool
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""
    # Captured by daemon when workdir is a git repo. Both empty for non-repo
    # runs or when nothing changed; backend just persists what's sent.
    diff_stat: str = ""
    diff: str = ""
    # Runtime-native session handle captured during dispatch (e.g. claude
    # session_id). Backend stores it on the agent profile so the next
    # dispatch can pass --resume <id> for conversation continuity.
    session_id: str = ""
    # Daemon-side filesystem path where the runtime ran. Surfaces in UI
    # so the user can navigate to the workdir.
    workdir: str = ""
    # AP-107: post-mortem diagnostics captured by the daemon at run-end.
    # Shape: {exit_code, stderr_tail, last_events_tail, captured_at}.
    # Surfaced via the get_run_diagnostics MCP tool. Optional — older
    # daemons that don't send this still work.
    diagnostics: Optional[dict] = None
    # paused=True: the run was parked mid-flight (SIGTERM), not finished.
    # Backend keeps the run PAUSED and only persists the session_id so a
    # later resume can relaunch with `claude --resume`.
    paused: bool = False
    # P1: the daemon confirmed it killed the subprocess in response to a
    # user-initiated cancel. Backend flips the run to CANCELLED and
    # suppresses the "execution failed" admin notification — this isn't a
    # failure, the user asked for it.
    cancelled: bool = False
    # Daemon's materializer outcome — "ok", "no_repo_path", or
    # "repo_path_not_found:<expanded>". Surfaces on the Run page so the
    # user knows when an agent ran in an empty scratch dir.
    materialize_reason: str = ""
    # AP-133: daemon retried without --resume because the stamped
    # session id wasn't found locally. Backend clears the stale id from
    # forge_conversations so the next dispatch doesn't reuse it.
    session_lost: bool = False
    # ADR 009 / AP-136: raw git work facts {tracked, untracked, committed}.
    # The backend maps these onto the project's work-signal setting to
    # decide whether a standalone (run-less) chat turn crystallizes into a
    # run. Empty/absent for older daemons — the turn just stays a turn.
    work_signal: dict = {}


class MessageCreate(BaseModel):
    role: str
    content: str
    run_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None
    tool_output: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model_used: str = ""


class ScheduleUpdate(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    tz: Optional[str] = None
    days: Optional[str] = None
    enabled: Optional[bool] = None


class CostEstimateRequest(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int


class RuntimeChatRequest(BaseModel):
    content: str
    run_id: Optional[str] = None
    # AP-76: per-call user-context bundle. Carries the surface, route,
    # and resolved project/task ids so the agent knows what the user is
    # looking at. Shape is intentionally loose — frontend evolves it
    # without backend schema changes. Backend uses project_id (if any)
    # to populate repo_path + MCP config on the dispatch frame, and
    # forwards the whole dict so the daemon can render it as a
    # synthetic system message.
    user_context: Optional[dict] = None
    # AP-105: when the user is continuing a conversation in a specific
    # scope (e.g. a finished task run's chat), pass scope_key explicitly
    # so backend picks the right session_id for resume. Without this,
    # scope would be computed from project_id and the run-scoped
    # conversation would diverge.
    scope_key: Optional[str] = None



# ── Runtime registration schemas ─────────────────────────────────────────

class RuntimeEntry(BaseModel):
    provider: str
    binary_path: str
    version: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    gateway_url: Optional[str] = None
    gateway_token: Optional[str] = None
    # Host-side discovered tools — opaque dict shape (see ForgeRuntime.host_tools).
    host_tools: Optional[dict] = None


class RuntimeRegisterRequest(BaseModel):
    daemon_id: str
    device_name: Optional[str] = None
    runtimes: list[RuntimeEntry]


class RuntimeHeartbeatRequest(BaseModel):
    daemon_id: str
    providers: list[str]  # which providers are still alive
    # ADR 009 / B4: the daemon's currently-live turns, so the backend has a
    # restart-proof view of what's running (and stoppable) per scope.
    inflight: list[dict] = []


# ── Runtime endpoints ─────────────────────────────────────────────────────

@daemon_router.post("/runtimes/register", status_code=200)
def register_runtimes(body: RuntimeRegisterRequest):
    return services.register_runtimes(
        daemon_id=body.daemon_id,
        device_name=body.device_name,
        runtimes=[r.model_dump() for r in body.runtimes],
    )


@daemon_router.post("/runtimes/heartbeat")
def runtime_heartbeat(body: RuntimeHeartbeatRequest):
    return services.heartbeat_runtimes(
        daemon_id=body.daemon_id, providers=body.providers,
        inflight=body.inflight,
    )


@daemon_router.post("/agents/{agent_id}/trigger-events")
def daemon_append_trigger_events(agent_id: str, body: DaemonTriggerEvents):
    return services.append_trigger_events(
        agent_id, trace_id=body.trace_id, run_id=body.run_id, events=body.events,
    )


@daemon_router.post("/agents/{agent_id}/trigger-complete")
def daemon_complete_trigger(agent_id: str, body: DaemonTriggerComplete):
    return services.complete_trigger(
        agent_id,
        trace_id=body.trace_id,
        run_id=body.run_id,
        success=body.success,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        error=body.error if not body.success else None,
        diff_stat=body.diff_stat,
        diff=body.diff,
        session_id=body.session_id,
        workdir=body.workdir,
        paused=body.paused,
        cancelled=body.cancelled,
        diagnostics=body.diagnostics,
        materialize_reason=body.materialize_reason,
        session_lost=body.session_lost,
        work_signal=body.work_signal,
    )


@router.get("/runtimes")
def list_runtimes(provider: Optional[str] = None, status: Optional[str] = None):
    return services.list_runtimes(provider=provider, status=status)


@router.get("/runtimes/{runtime_id}")
def get_runtime(runtime_id: str):
    result = services.get_runtime(runtime_id)
    if not result:
        raise HTTPException(404, "Runtime not found")
    return result


# ── MCP server registry ──────────────────────────────────────────────────

@router.get("/mcp-servers")
def list_mcp_servers(include_auto: bool = False):
    """Available MCP servers for the agent toolkit picker. By default
    hides auto-injected servers (agentira, memory) — those ride on every
    run regardless of the agent's selection."""
    return services.list_mcp_servers(include_auto=include_auto)


# ── Agent endpoints ──────────────────────────────────────────────────────

@router.get("/agents")
def list_agents(status: Optional[str] = None):
    return services.list_agents(status=status)


@router.post("/agents", status_code=201)
def create_agent(body: AgentCreate):
    return services.create_agent(
        profile_id=body.profile_id,
        name=body.name,
        executor_type=body.executor_type,
        model=body.model,
        webhook_url=body.webhook_url,
        config_json=body.config_json,
        runtime_id=body.runtime_id,
    )


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    result = services.get_agent(agent_id)
    if not result:
        raise HTTPException(404, "Agent not found")
    return result


@router.get("/agents/{agent_id}/projects")
def list_agent_projects(agent_id: str):
    """Projects this agent is a member of (resolved via the 1:1 profile)."""
    return services.list_agent_projects(agent_id)


@router.get("/agents/{agent_id}/conversation")
def get_conversation(agent_id: str, project_id: Optional[str] = None,
                     task_id: Optional[str] = None):
    """Conversation state for a given (agent, scope): scope_key, whether a
    runtime session has been captured (and thus next dispatch will resume),
    and how many messages live in this scope."""
    return services.get_conversation_info(
        agent_id=agent_id, project_id=project_id, task_id=task_id,
    )


@router.get("/agents/{agent_id}/dispatch-preview")
def dispatch_preview(agent_id: str, project_id: Optional[str] = None):
    """Dry-run what a chat dispatch would send to the daemon for this agent.

    Returns the resolved repo_path, conventions snippet, MCP server list,
    env vars, and system-prompt addenda. UI uses this for the /context
    inspector so users can see what's being sent without firing a run.
    """
    return services.dispatch_preview(agent_id, project_id=project_id)


@router.patch("/agents/{agent_id}")
def update_agent(agent_id: str, body: AgentUpdate):
    fields = body.model_dump(exclude_none=True)
    try:
        result = services.update_agent(agent_id, **fields)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not result:
        raise HTTPException(404, "Agent not found")
    # If the Conductor's cadence changed, re-install the scheduler jobs
    # so the new interval takes effect without a backend restart.
    if "conductor_tick_seconds" in fields \
            or "conductor_plan_interval_minutes" in fields \
            or "conductor_report_time" in fields \
            or "conductor_report_enabled" in fields:
        try:
            from backend.forge.scheduler import scheduler
            scheduler.refresh()
        except Exception:
            pass
    return result


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str):
    try:
        deleted = services.delete_agent(agent_id)
    except ValueError as exc:
        # System agents (Conductor, Concierge) are protected.
        raise HTTPException(403, str(exc))
    if not deleted:
        raise HTTPException(404, "Agent not found")
    return {"ok": True}


@router.get("/concierge")
def get_concierge():
    """The system Concierge agent — seeded on demand. Powers the floating
    chat on both Studio and Forge; the frontend resolves the agent id here."""
    from backend.forge import concierge as _concierge
    info = _concierge.get_or_create_concierge()
    if info.get("error"):
        raise HTTPException(503, info["error"])
    agent = services.get_agent(info["id"])
    if not agent:
        raise HTTPException(404, "Concierge not available")
    return agent


@router.post("/agents/{agent_id}/heartbeat")
def agent_heartbeat(agent_id: str, body: HeartbeatRequest):
    result = services.heartbeat(agent_id, status=body.status)
    if not result:
        raise HTTPException(404, "Agent not found")
    return result


# ── Run endpoints ────────────────────────────────────────────────────────

@router.get("/runs")
def list_runs(agent_id: Optional[str] = None, project_id: Optional[str] = None,
              status: Optional[str] = None, limit: int = 100, offset: int = 0):
    return services.list_runs(agent_id=agent_id, project_id=project_id,
                              status=status, limit=limit, offset=offset)


@router.post("/runs", status_code=201)
def create_run(body: RunCreate):
    return services.create_run(
        agent_id=body.agent_id,
        task_id=body.task_id,
        project_id=body.project_id,
        trigger_event=body.trigger_event,
        model_used=body.model_used,
    )


class ScheduleTaskRunRequest(BaseModel):
    agent_id: str


@router.post("/tasks/{task_id}/run", status_code=201)
async def schedule_task_run(task_id: str, body: ScheduleTaskRunRequest):
    """Schedule a Run against a task with the chosen agent.

    Builds the prompt from task content (title + description + DoD),
    creates a Run row, and dispatches the trigger that the daemon picks up.

    `async def` is mandatory: the service calls `asyncio.ensure_future`
    on the WS hub dispatch coroutine, which requires a running loop in
    the current thread. Sync handlers run in a worker thread with no
    loop, so the dispatch silently no-ops.
    """
    result = services.schedule_task_run(task_id=task_id, agent_id=body.agent_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/tasks/{task_id}/prepare-run", status_code=201)
def prepare_task_run(task_id: str, body: ScheduleTaskRunRequest):
    """AP-112: build the prompt, create a READY Run, do NOT dispatch.

    The client navigates to /forge/runs/<id>, lets the user edit the
    prompt, then calls POST /runs/<id>/dispatch to start.
    """
    result = services.prepare_task_run(task_id=task_id, agent_id=body.agent_id)
    # NB: `_run_to_dict` always includes "error": None for clean runs, so
    # check the value (truthy = real error string), not key membership.
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


class DispatchRunRequest(BaseModel):
    prompt: Optional[str] = None


@router.post("/runs/{run_id}/dispatch")
async def dispatch_pending_run(run_id: str, body: Optional[DispatchRunRequest] = None):
    """AP-112: start a READY/PENDING run, optionally with an edited prompt.

    `async def` is mandatory — the service schedules the WS dispatch
    coroutine, which needs a running loop in the current thread."""
    override = body.prompt if body else None
    result = services.dispatch_pending_run(run_id=run_id, prompt_override=override)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.post("/runs/{run_id}/discard")
def discard_pending_run(run_id: str):
    """AP-112: delete a never-dispatched READY run."""
    result = services.discard_pending_run(run_id=run_id)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.get("/runs/{run_id}/ready-checks")
def run_ready_checks(run_id: str):
    """AP-113: pre-run validation checklist for a READY run — runtime,
    API key, MCP, environment/keys, repo, task context."""
    result = services.ready_checks(run_id)
    if result.get("error"):
        raise HTTPException(404, result["error"])
    return result


@router.get("/tasks/{task_id}/runs")
def list_task_runs(task_id: str):
    return services.list_runs_for_task(task_id)


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    result = services.get_run(run_id)
    if not result:
        raise HTTPException(404, "Run not found")
    return result


@router.get("/triggers/{trace_id}/events")
def get_trigger_events(trace_id: str):
    """Messages tagged with this trace_id, ordered by creation time."""
    return services.get_trigger_events(trace_id)


@router.get("/runs/{run_id}/events")
def get_run_events(run_id: str):
    """Messages tagged with this run_id (across all of its triggers)."""
    return services.get_run_events(run_id)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel a pending/running Run. Marks it cancelled immediately and
    fires a cancel signal to the daemon to kill any in-flight subprocess."""
    result = services.cancel_run(run_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str):
    """Pause a running CLI subprocess (SIGSTOP). Async required so the
    WS dispatch coroutine has a loop to schedule on."""
    result = services.pause_run(run_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str):
    """Resume a paused CLI subprocess (SIGCONT)."""
    result = services.resume_run(run_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/runs/{run_id}/start")
def start_run(run_id: str):
    result = services.start_run(run_id)
    if not result:
        raise HTTPException(404, "Run not found")
    return result


@router.post("/runs/{run_id}/complete")
def complete_run(run_id: str, body: RunComplete):
    result = services.complete_run(
        run_id,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        cost_usd=body.cost_usd,
        error=body.error,
    )
    if not result:
        raise HTTPException(404, "Run not found")
    return result


# ── Stats ────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats():
    return services.get_stats()


# ── Conductor ────────────────────────────────────────────────────────────

@router.get("/conductor")
def conductor_status():
    """Conductor state for the management UI: identity, cadence config,
    last tick + last report results, and a live survey of conductor-
    enabled agents + their next task."""
    from backend.forge import conductor as _conductor
    return {
        "conductor": _conductor.get_or_create_conductor(),
        "tick_interval_s": _conductor.TICK_INTERVAL_S,
        "config": _conductor.get_conductor_config(),
        "last_tick": _conductor.get_last_tick(),
        "last_report": _conductor.get_last_report(),
        "last_plan": _conductor.get_last_plan(),
        "survey": _conductor.survey_workspace(),
    }


@router.post("/conductor/tick")
def conductor_tick_now():
    """Run one Conductor tick immediately (manual nudge from the UI)."""
    from backend.forge import conductor as _conductor
    return _conductor.run_tick()


@router.post("/conductor/report")
def conductor_report_now():
    """Compile + post the Conductor's daily report immediately (manual
    nudge from the UI). Dispatches one LLM turn to the Conductor agent."""
    from backend.forge import conductor as _conductor
    return _conductor.run_daily_report()


@router.post("/conductor/plan")
def conductor_plan_now():
    """Run the Conductor's LLM planning turn immediately — assigns the
    unassigned todo backlog to agents. Self-skips if nothing to plan."""
    from backend.forge import conductor as _conductor
    return _conductor.run_planning_turn()


@router.get("/projects/{project_id}/digest")
def get_project_digest(project_id: str, since: str = "24h"):
    """AP-84: aggregated run summary for a project over a recent window.

    `since` accepts `Nh` (hours), `Nd` (days), or an ISO timestamp.
    Powers the dashboard digest panel.
    """
    from backend.forge.digest import generate_digest
    result = generate_digest(project_id=project_id, since=since)
    if isinstance(result, dict) and result.get("error") == "project_not_found":
        raise HTTPException(404, "Project not found")
    return result


@router.get("/projects/{project_id}/activity")
def get_project_activity(project_id: str, since: str = "24h"):
    """AP-74: live activity summary for a project — the run digest plus
    the Conductor's view of this project (its conductor-enabled agents,
    their in-flight load, and each one's next task). Polled by the
    project summary panel for dynamic, current state."""
    from backend.forge.digest import generate_digest
    from backend.forge import conductor as _conductor
    digest = generate_digest(project_id=project_id, since=since)
    if isinstance(digest, dict) and digest.get("error") == "project_not_found":
        raise HTTPException(404, "Project not found")
    survey = _conductor.survey_workspace()
    agents = [a for a in survey.get("agents", [])
              if a.get("project_id") == project_id]
    try:
        cfg = _conductor.get_conductor_config()
    except Exception:
        cfg = {}
    return {
        "digest": digest,
        "conductor": {
            "agents": agents,
            "tick_seconds": cfg.get("tick_seconds"),
        },
    }


# ── Message endpoints ───────────────────────────────────────────────────

@router.get("/agents/{agent_id}/messages")
def list_messages(agent_id: str, run_id: Optional[str] = None,
                  scope_key: Optional[str] = None,
                  limit: int = 100, offset: int = 0):
    return services.list_messages(
        agent_id, run_id=run_id, scope_key=scope_key,
        limit=limit, offset=offset,
    )


@router.get("/agents/{agent_id}/conversations")
def list_conversations(agent_id: str):
    return services.list_conversations(agent_id)


# ── ADR 008: chat controls (clear + stop) ──────────────────────────────

@router.post("/agents/{agent_id}/conversations/clear")
def clear_conversation(agent_id: str, body: dict):
    scope_key = (body or {}).get("scope_key", "")
    if not scope_key:
        raise HTTPException(400, "scope_key required")
    return services.clear_conversation(agent_id=agent_id, scope_key=scope_key)


@router.post("/agents/{agent_id}/chat/stop")
def stop_chat(agent_id: str, body: dict):
    scope_key = (body or {}).get("scope_key", "")
    if not scope_key:
        raise HTTPException(400, "scope_key required")
    return services.stop_chat(agent_id=agent_id, scope_key=scope_key)


@router.post("/agents/{agent_id}/messages", status_code=201)
def create_message(agent_id: str, body: MessageCreate):
    return services.create_message(
        agent_id=agent_id, role=body.role, content=body.content,
        run_id=body.run_id, tool_name=body.tool_name,
        tool_input=body.tool_input, tool_output=body.tool_output,
        input_tokens=body.input_tokens, output_tokens=body.output_tokens,
        cost_usd=body.cost_usd, model_used=body.model_used,
    )


# ── Webhook log endpoints ──────────────────────────────────────────────

@router.get("/agents/{agent_id}/webhook-logs")
def list_webhook_logs(agent_id: str, limit: int = 50, offset: int = 0):
    return services.list_webhook_logs(agent_id, limit=limit, offset=offset)


# ── Schedule endpoints ──────────────────────────────────────────────────

@router.put("/agents/{agent_id}/schedule")
def update_schedule(agent_id: str, body: ScheduleUpdate):
    result = services.update_schedule(
        agent_id, start=body.start, end=body.end,
        tz=body.tz, days=body.days, enabled=body.enabled,
    )
    if not result:
        raise HTTPException(404, "Agent not found")
    return result


# ── Cost endpoints ──────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/costs")
def get_agent_costs(agent_id: str):
    return services.get_agent_cost_breakdown(agent_id)


@router.post("/cost-estimate")
def cost_estimate(body: CostEstimateRequest):
    return services.estimate_cost(body.model, body.input_tokens, body.output_tokens)


@router.get("/pricing")
def get_pricing():
    return services.get_model_pricing()


# ── OpenClaw integration endpoints ──────────────────────────────────────

@router.get("/agents/{agent_id}/runtime/status")
def runtime_status(agent_id: str):
    return services.get_runtime_status(agent_id)


@router.post("/agents/{agent_id}/runtime/chat")
async def runtime_chat(agent_id: str, body: RuntimeChatRequest):
    return services.send_runtime_message(
        agent_id,
        content=body.content,
        run_id=body.run_id,
        user_context=body.user_context,
        scope_key=body.scope_key,
    )


@router.get("/openclaw/overview")
def openclaw_overview():
    """Full OpenClaw overview: health, agents, sessions, costs."""
    return services.get_openclaw_overview()


@router.post("/openclaw/sync")
def openclaw_sync():
    """Sync OpenClaw agent data (models, status) into Forge agents."""
    return services.sync_openclaw_agents()


@router.get("/agents/{agent_id}/runtime/sessions")
def runtime_sessions(agent_id: str):
    """Pull live sessions + activity from the agent's runtime."""
    return services.get_runtime_sessions(agent_id)


@router.get("/agents/{agent_id}/runtime/costs")
def runtime_costs(agent_id: str):
    """Pull cost/usage data from the agent's runtime."""
    return services.get_runtime_costs(agent_id)


class ModelUpdateRequest(BaseModel):
    agent_name: str
    model: str


@router.get("/openclaw/models")
def openclaw_models():
    """Available models from OpenClaw config + pricing table."""
    return services.get_openclaw_models()


@router.post("/openclaw/agent-model")
def set_openclaw_model(body: ModelUpdateRequest):
    """Update an agent's model in openclaw.json and Forge DB."""
    result = services.set_openclaw_agent_model(body.agent_name, body.model)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "Failed"))
    return result


@router.post("/agents/{agent_id}/reset-status")
def reset_agent_status(agent_id: str):
    """Force-reset agent status. Unsticks BUSY agents with no active runs,
    and fails any orphaned RUNNING/PENDING runs."""
    result = services.reset_agent_status(agent_id)
    if not result:
        raise HTTPException(404, "Agent not found")
    return result


# ── Scheduler ───────────────────────────────────────────────────────────

@router.post("/scheduler/refresh")
def refresh_scheduler():
    """Re-read agent cron schedules and rebuild APScheduler jobs."""
    try:
        from backend.forge.scheduler import scheduler
        return scheduler.refresh()
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Daemon WebSocket ─────────────────────────────────────────────────────

@daemon_router.websocket("/daemon/ws")
async def daemon_ws(ws: WebSocket):
    """Persistent WebSocket for daemon ↔ server push.

    Daemon sends: {"daemon_id": "...", "runtime_ids": ["rid1", ...]}
    Server sends: {"type": "task_available", "task_id": "...", "runtime_id": "..."}
    """
    from backend.forge.ws_dispatch import handle_daemon_ws
    await handle_daemon_ws(ws)


# P4: browser WS — subscribe to live run-status updates so RunDetail
# doesn't have to wait for the 5s poll. Sits under `daemon_router`
# (which is auth-free) because browser WebSockets can't send the
# Authorization header — auth on this channel is the unguessable run_id
# itself, same model as the existing /daemon/ws. Read-only; no
# server-trust on inbound frames.
@daemon_router.websocket("/ws/runs/{run_id}")
async def client_run_ws(ws: WebSocket, run_id: str):
    """Browser subscribes to run-status updates for a single run."""
    from backend.forge.ws_dispatch import handle_client_run_ws
    await handle_client_run_ws(ws, run_id)


# ── WS hub status (debugging) ────────────────────────────────────────────

@router.get("/daemon/connections")
def daemon_connections():
    """List currently connected daemon IDs (debug endpoint)."""
    from backend.forge.ws_dispatch import hub
    return {"connected": hub.connected_daemon_ids()}

