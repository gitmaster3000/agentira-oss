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
    profile_id: Optional[str] = None
    executor_type: str = "http"
    model: str = ""
    webhook_url: str = ""
    config_json: Optional[str] = None
    runtime_id: Optional[str] = None


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



# ── Runtime registration schemas ─────────────────────────────────────────

class RuntimeEntry(BaseModel):
    provider: str
    binary_path: str
    version: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    gateway_url: Optional[str] = None
    gateway_token: Optional[str] = None


class RuntimeRegisterRequest(BaseModel):
    daemon_id: str
    device_name: Optional[str] = None
    runtimes: list[RuntimeEntry]


class RuntimeHeartbeatRequest(BaseModel):
    daemon_id: str
    providers: list[str]  # which providers are still alive


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
    return services.heartbeat_runtimes(daemon_id=body.daemon_id, providers=body.providers)


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


@router.patch("/agents/{agent_id}")
def update_agent(agent_id: str, body: AgentUpdate):
    result = services.update_agent(agent_id, **body.model_dump(exclude_none=True))
    if not result:
        raise HTTPException(404, "Agent not found")
    return result


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str):
    if not services.delete_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    return {"ok": True}


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


# ── Message endpoints ───────────────────────────────────────────────────

@router.get("/agents/{agent_id}/messages")
def list_messages(agent_id: str, run_id: Optional[str] = None,
                  limit: int = 100, offset: int = 0):
    return services.list_messages(agent_id, run_id=run_id, limit=limit, offset=offset)


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
    return services.send_runtime_message(agent_id, content=body.content, run_id=body.run_id)


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


# ── WS hub status (debugging) ────────────────────────────────────────────

@router.get("/daemon/connections")
def daemon_connections():
    """List currently connected daemon IDs (debug endpoint)."""
    from backend.forge.ws_dispatch import hub
    return {"connected": hub.connected_daemon_ids()}

