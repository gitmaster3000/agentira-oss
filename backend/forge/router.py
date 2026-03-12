"""Forge API router — mounted under /api/forge."""

from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.forge import services

router = APIRouter(prefix="/api/forge", tags=["forge"])


# ── Schemas ──────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    profile_id: str
    name: str
    executor_type: str = "http"
    model: str = ""
    webhook_url: str = ""
    config_json: Optional[str] = None


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    executor_type: Optional[str] = None
    model: Optional[str] = None
    status: Optional[str] = None
    webhook_url: Optional[str] = None
    config_json: Optional[str] = None


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


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    result = services.get_run(run_id)
    if not result:
        raise HTTPException(404, "Run not found")
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
