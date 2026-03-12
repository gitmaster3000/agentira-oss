"""Forge service layer — business logic for Agents and Runs."""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db import SessionLocal
from backend.forge.models import Agent, Run, AgentStatus, RunStatus


def _session() -> Session:
    return SessionLocal()


# ── Serializers ──────────────────────────────────────────────────────────

def _agent_to_dict(a: Agent) -> dict:
    return {
        "id": a.id,
        "profile_id": a.profile_id,
        "profile_name": a.profile.name if a.profile else None,
        "name": a.name,
        "executor_type": a.executor_type,
        "model": a.model,
        "status": a.status.value,
        "webhook_url": a.webhook_url,
        "last_heartbeat": a.last_heartbeat.isoformat() if a.last_heartbeat else None,
        "total_runs": a.total_runs,
        "total_cost_usd": a.total_cost_usd,
        "created_at": a.created_at.isoformat(),
    }


def _run_to_dict(r: Run) -> dict:
    return {
        "id": r.id,
        "agent_id": r.agent_id,
        "agent_name": r.agent.name if r.agent else None,
        "task_id": r.task_id,
        "task_title": r.task.title if r.task else None,
        "project_id": r.project_id,
        "project_name": r.project.name if r.project else None,
        "trigger_event": r.trigger_event,
        "status": r.status.value,
        "model_used": r.model_used,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "duration_ms": r.duration_ms,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "cost_usd": r.cost_usd,
        "error": r.error,
        "created_at": r.created_at.isoformat(),
    }


# ── Agents ───────────────────────────────────────────────────────────────

def list_agents(status: Optional[str] = None) -> list[dict]:
    with _session() as db:
        q = db.query(Agent)
        if status:
            q = q.filter(Agent.status == status)
        return [_agent_to_dict(a) for a in q.order_by(Agent.created_at.desc()).all()]


def get_agent(agent_id: str) -> dict | None:
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        return _agent_to_dict(a) if a else None


def create_agent(*, profile_id: str, name: str, executor_type: str = "http",
                 model: str = "", webhook_url: str = "", config_json: str | None = None) -> dict:
    with _session() as db:
        a = Agent(
            profile_id=profile_id,
            name=name,
            executor_type=executor_type,
            model=model,
            webhook_url=webhook_url,
            config_json=config_json,
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        return _agent_to_dict(a)


def update_agent(agent_id: str, **fields) -> dict | None:
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return None
        for k, v in fields.items():
            if v is not None and hasattr(a, k):
                setattr(a, k, v)
        db.commit()
        db.refresh(a)
        return _agent_to_dict(a)


def delete_agent(agent_id: str) -> bool:
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return False
        db.delete(a)
        db.commit()
        return True


def heartbeat(agent_id: str, status: str = "online") -> dict | None:
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return None
        a.last_heartbeat = datetime.now(timezone.utc)
        a.status = AgentStatus(status)
        db.commit()
        db.refresh(a)
        return _agent_to_dict(a)


# ── Runs ─────────────────────────────────────────────────────────────────

def list_runs(*, agent_id: Optional[str] = None, project_id: Optional[str] = None,
              status: Optional[str] = None, limit: int = 100, offset: int = 0) -> list[dict]:
    with _session() as db:
        q = db.query(Run)
        if agent_id:
            q = q.filter(Run.agent_id == agent_id)
        if project_id:
            q = q.filter(Run.project_id == project_id)
        if status:
            q = q.filter(Run.status == status)
        runs = q.order_by(Run.created_at.desc()).offset(offset).limit(limit).all()
        return [_run_to_dict(r) for r in runs]


def get_run(run_id: str) -> dict | None:
    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        return _run_to_dict(r) if r else None


def create_run(*, agent_id: str, task_id: str | None = None,
               project_id: str | None = None, trigger_event: str = "",
               model_used: str = "") -> dict:
    with _session() as db:
        r = Run(
            agent_id=agent_id,
            task_id=task_id,
            project_id=project_id,
            trigger_event=trigger_event,
            status=RunStatus.PENDING,
            model_used=model_used,
        )
        db.add(r)
        db.commit()
        db.refresh(r)
        return _run_to_dict(r)


def start_run(run_id: str) -> dict | None:
    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return None
        r.status = RunStatus.RUNNING
        r.started_at = datetime.now(timezone.utc)
        # Mark agent busy
        if r.agent:
            r.agent.status = AgentStatus.BUSY
        db.commit()
        db.refresh(r)
        return _run_to_dict(r)


def complete_run(run_id: str, *, input_tokens: int = 0, output_tokens: int = 0,
                 cost_usd: float = 0.0, error: str | None = None) -> dict | None:
    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return None
        now = datetime.now(timezone.utc)
        r.status = RunStatus.FAILED if error else RunStatus.COMPLETED
        r.finished_at = now
        r.input_tokens = input_tokens
        r.output_tokens = output_tokens
        r.cost_usd = cost_usd
        r.error = error
        if r.started_at:
            r.duration_ms = int((now - r.started_at).total_seconds() * 1000)
        # Update agent stats
        if r.agent:
            r.agent.status = AgentStatus.ONLINE
            r.agent.total_runs += 1
            r.agent.total_cost_usd += cost_usd
        db.commit()
        db.refresh(r)
        return _run_to_dict(r)


# ── Stats ────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    with _session() as db:
        total_agents = db.query(func.count(Agent.id)).scalar() or 0
        online_agents = db.query(func.count(Agent.id)).filter(Agent.status == AgentStatus.ONLINE).scalar() or 0
        busy_agents = db.query(func.count(Agent.id)).filter(Agent.status == AgentStatus.BUSY).scalar() or 0

        total_runs = db.query(func.count(Run.id)).scalar() or 0
        completed_runs = db.query(func.count(Run.id)).filter(Run.status == RunStatus.COMPLETED).scalar() or 0
        failed_runs = db.query(func.count(Run.id)).filter(Run.status == RunStatus.FAILED).scalar() or 0
        running_now = db.query(func.count(Run.id)).filter(Run.status == RunStatus.RUNNING).scalar() or 0

        total_cost = db.query(func.sum(Run.cost_usd)).scalar() or 0.0
        total_input_tokens = db.query(func.sum(Run.input_tokens)).scalar() or 0
        total_output_tokens = db.query(func.sum(Run.output_tokens)).scalar() or 0

        return {
            "agents": {"total": total_agents, "online": online_agents, "busy": busy_agents},
            "runs": {
                "total": total_runs,
                "completed": completed_runs,
                "failed": failed_runs,
                "running": running_now,
                "success_rate": round(completed_runs / total_runs * 100, 1) if total_runs else 0,
            },
            "cost": {"total_usd": round(total_cost, 4)},
            "tokens": {"input": total_input_tokens, "output": total_output_tokens},
        }
