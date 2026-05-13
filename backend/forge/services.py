"""Forge service layer — business logic for Agents, Runs, Messages, Webhooks."""

from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.db import SessionLocal
from backend.models import Profile, Role
from backend.forge.models import (
    Agent, Run, AgentMessage, WebhookLog,
    AgentStatus, RunStatus, RunOutcome, MessageRole,
    ForgeRuntime, RuntimeStatus,
)


def _session() -> Session:
    return SessionLocal()


def _utc(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is timezone-aware (UTC). Handles naive DB values."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    """ISO timestamp with explicit UTC suffix; safe for browser Date()."""
    aware = _utc(dt)
    return aware.isoformat() if aware else None


# ── Serializers ──────────────────────────────────────────────────────────

def _sync_bots(db) -> None:
    """AP-86: maintain 1:1 link between bot profile and Agent. Same id.

    For each bot profile, ensure exactly one Agent row exists sharing that
    id. Runtime fields mirror from profile (post-merge source of truth).
    Skips orphans (Agent rows whose profile_id was deleted).
    """
    bot_role = db.query(Role).filter(Role.name == "bot").first()
    if not bot_role:
        return
    bots = db.query(Profile).filter(Profile.role_id == bot_role.id).all()
    # Index existing agents by profile_id and by id; same-id is the new
    # invariant but we tolerate old random-id rows during transition.
    existing_by_pid = {a.profile_id: a for a in db.query(Agent).all() if a.profile_id}
    for bot in bots:
        agent = existing_by_pid.get(bot.id)
        if agent is None:
            agent = Agent(
                id=bot.id,                # AP-86: 1:1, same id
                profile_id=bot.id,
                name=bot.display_name or bot.name,
                webhook_url=bot.webhook_url or "",
            )
            db.add(agent)
        # Mirror runtime config from profile onto the agent so the OLD
        # code paths that read agent.model / agent.runtime_id keep working
        # during transition. New code should read from profile directly.
        agent.name = bot.display_name or bot.name
        if bot.model:
            agent.model = bot.model
        if bot.system_prompt is not None:
            agent.system_prompt = bot.system_prompt
        if bot.personality is not None:
            agent.personality = bot.personality
        if bot.runtime_id:
            agent.runtime_id = bot.runtime_id
        if bot.default_project_id:
            agent.default_project_id = bot.default_project_id
        if bot.mcp_servers:
            agent.mcp_servers = bot.mcp_servers
    db.commit()


def _agent_to_dict(a: Agent, runtime_cost: float | None = None) -> dict:
    # Pull live webhook_url from profile (source of truth)
    profile_webhook = a.profile.webhook_url if a.profile else ""
    # Liveness comes only from the WS hub — daemon connected = agent live.
    runtime_live = bool(a.runtime_id and a.runtime and _is_runtime_online(a.runtime))
    live_heartbeat = datetime.now(timezone.utc) if runtime_live else None
    # Derived status for new-model agents; legacy agents fall back to DB value.
    if a.runtime_id:
        derived_status = "online" if runtime_live else "offline"
    else:
        derived_status = a.status.value
    return {
        "id": a.id,
        "profile_id": a.profile_id,
        "profile_name": a.profile.name if a.profile else None,
        "display_name": a.profile.display_name if a.profile else None,
        "name": a.name,
        "executor_type": a.executor_type,
        "model": a.model,
        "status": derived_status,
        "webhook_url": profile_webhook or a.webhook_url,
        "last_heartbeat": _iso(live_heartbeat),
        "total_runs": a.total_runs,
        "total_cost_usd": runtime_cost if runtime_cost is not None else a.total_cost_usd,
        "system_prompt": a.system_prompt or "",
        "personality": a.personality or "",
        "schedule_start": a.schedule_start or "08:00",
        "schedule_end": a.schedule_end or "12:00",
        "schedule_tz": a.schedule_tz or "UTC",
        "schedule_days": a.schedule_days or "mon,tue,wed,thu,fri",
        "schedule_enabled": bool(a.schedule_enabled),
        "runtime_type": a.runtime_type or "openclaw",
        "runtime_url": a.runtime_url or "",
        "runtime_gateway_token": a.runtime_gateway_token or "",
        "runtime_hooks_token": a.runtime_hooks_token or "",
        "runtime_agent_name": a.runtime_agent_name or "",
        "runtime_id": a.runtime_id,
        "default_project_id": a.default_project_id,
        "schedule_cron": a.schedule_cron or "",
        "mcp_servers": json.loads(a.mcp_servers) if a.mcp_servers else [],
        "created_at": _iso(a.created_at),
    }


def _message_to_dict(m: AgentMessage) -> dict:
    return {
        "id": m.id,
        "agent_id": m.agent_id,
        "run_id": m.run_id,
        "trace_id": m.trace_id,
        "kind": m.kind,
        "role": m.role.value,
        "content": m.content,
        "tool_name": m.tool_name,
        "tool_input": m.tool_input,
        "tool_output": m.tool_output,
        "input_tokens": m.input_tokens,
        "output_tokens": m.output_tokens,
        "cost_usd": m.cost_usd,
        "model_used": m.model_used,
        "created_at": _iso(m.created_at),
    }


def _webhook_log_to_dict(w: WebhookLog) -> dict:
    return {
        "id": w.id,
        "agent_id": w.agent_id,
        "direction": w.direction,
        "url": w.url,
        "event": w.event,
        "payload": w.payload,
        "status_code": w.status_code,
        "response_body": w.response_body,
        "success": w.success,
        "duration_ms": w.duration_ms,
        "created_at": _iso(w.created_at),
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
        "outcome": r.outcome.value if r.outcome else None,
        "summary": r.summary or "",
        "diff_stat": r.diff_stat or "",
        "diff": r.diff or "",
        "model_used": r.model_used,
        "started_at": _iso(r.started_at),
        "finished_at": _iso(r.finished_at),
        "duration_ms": r.duration_ms,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "cost_usd": r.cost_usd,
        "error": r.error,
        "created_at": _iso(r.created_at),
    }


# ── Runtime serializer ──────────────────────────────────────────────────

def _runtime_to_dict(r: ForgeRuntime) -> dict:
    live = _is_runtime_online(r)
    return {
        "id": r.id,
        "daemon_id": r.daemon_id,
        "device_name": r.device_name,
        "provider": r.provider,
        "binary_path": r.binary_path,
        "version": r.version,
        "status": "online" if live else "offline",
        "capabilities": json.loads(r.capabilities) if r.capabilities else [],
        "models": json.loads(r.models) if r.models else [],
        "gateway_url": r.gateway_url or "",
        "gateway_token": r.gateway_token or "",
        "last_heartbeat": _iso(datetime.now(timezone.utc)) if live else None,
        "created_at": _iso(r.created_at),
    }


# ── Runtime CRUD ─────────────────────────────────────────────────────────

def register_runtimes(daemon_id: str, device_name: str | None, runtimes: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    with _session() as db:
        results = []
        for entry in runtimes:
            existing = (
                db.query(ForgeRuntime)
                .filter_by(daemon_id=daemon_id, provider=entry["provider"])
                .first()
            )
            if existing:
                existing.binary_path = entry["binary_path"]
                existing.version = entry.get("version")
                existing.capabilities = json.dumps(entry.get("capabilities", []))
                existing.models = json.dumps(entry.get("models", []))
                existing.gateway_url = entry.get("gateway_url") or None
                existing.gateway_token = entry.get("gateway_token") or None
                existing.status = RuntimeStatus.ONLINE
                existing.last_heartbeat = now
                if device_name:
                    existing.device_name = device_name
                results.append(_runtime_to_dict(existing))
            else:
                rt = ForgeRuntime(
                    daemon_id=daemon_id,
                    device_name=device_name,
                    provider=entry["provider"],
                    binary_path=entry["binary_path"],
                    version=entry.get("version"),
                    capabilities=json.dumps(entry.get("capabilities", [])),
                    models=json.dumps(entry.get("models", [])),
                    gateway_url=entry.get("gateway_url") or None,
                    gateway_token=entry.get("gateway_token") or None,
                    status=RuntimeStatus.ONLINE,
                    last_heartbeat=now,
                )
                db.add(rt)
                db.flush()
                results.append(_runtime_to_dict(rt))
        db.commit()
        return {"registered": results}


def heartbeat_runtimes(daemon_id: str, providers: list[str]) -> dict:
    now = datetime.now(timezone.utc)
    with _session() as db:
        updated = (
            db.query(ForgeRuntime)
            .filter(
                ForgeRuntime.daemon_id == daemon_id,
                ForgeRuntime.provider.in_(providers),
            )
            .all()
        )
        for rt in updated:
            rt.status = RuntimeStatus.ONLINE
            rt.last_heartbeat = now
        db.commit()
        return {"updated": len(updated)}


def list_runtimes(provider: str | None = None, status: str | None = None) -> list[dict]:
    with _session() as db:
        q = db.query(ForgeRuntime)
        if provider:
            q = q.filter(ForgeRuntime.provider == provider)
        if status:
            q = q.filter(ForgeRuntime.status == status)
        return [_runtime_to_dict(r) for r in q.order_by(ForgeRuntime.created_at.desc()).all()]


def get_runtime(runtime_id: str) -> dict | None:
    with _session() as db:
        rt = db.get(ForgeRuntime, runtime_id)
        return _runtime_to_dict(rt) if rt else None


# ── Live status probe ────────────────────────────────────────────────────

_HEARTBEAT_TIMEOUT_S = 120  # offline if no heartbeat in 2 minutes


def _has_active_runs(db, agent_id: str) -> bool:
    """Check if agent has any RUNNING or PENDING runs."""
    return (db.query(Run)
            .filter(Run.agent_id == agent_id,
                    Run.status.in_([RunStatus.RUNNING, RunStatus.PENDING]))
            .first()) is not None


def _is_runtime_online(rt: "ForgeRuntime | None") -> bool:
    """Runtime is online iff its daemon's WS is currently connected."""
    if rt is None:
        return False
    from backend.forge.ws_dispatch import hub
    return hub.is_connected(rt.daemon_id)


def _resolve_agent_status(a: Agent, runtime_online: bool, db) -> AgentStatus:
    """Determine correct status for an agent given runtime health.

    Priority: bound forge_runtime → legacy runtime_url → heartbeat staleness.
    Unsticks BUSY agents with no active runs.
    """
    now = datetime.now(timezone.utc)

    # BUSY is only valid if there's an active run
    if a.status == AgentStatus.BUSY and not _has_active_runs(db, a.id):
        return AgentStatus.ONLINE if runtime_online else AgentStatus.OFFLINE

    # If agent is legitimately busy, keep it
    if a.status == AgentStatus.BUSY:
        return AgentStatus.BUSY

    # New model: agent bound to a forge_runtime — mirror daemon health
    if a.runtime_id:
        return AgentStatus.ONLINE if _is_runtime_online(a.runtime) else AgentStatus.OFFLINE

    # Legacy: HTTP gateway agent
    if a.runtime_url:
        return AgentStatus.ONLINE if runtime_online else AgentStatus.OFFLINE

    # Fallback: heartbeat staleness
    if a.last_heartbeat:
        age_s = (now - _utc(a.last_heartbeat)).total_seconds()
        return AgentStatus.ONLINE if age_s < _HEARTBEAT_TIMEOUT_S else AgentStatus.OFFLINE
    return AgentStatus.OFFLINE


def _refresh_status(db, agents: list[Agent]) -> dict[str, float]:
    """Ping each unique gateway, update heartbeat, pull live costs.

    Returns: {agent_id: runtime_cost_usd} for agents with live cost data.
    """
    from backend.forge import runtime_client

    now = datetime.now(timezone.utc)
    live_costs: dict[str, float] = {}

    # One health check per unique runtime_url
    url_online: dict[str, bool] = {}
    for a in agents:
        url = a.runtime_url
        if url and url not in url_online:
            health = runtime_client.check_health(url, a.runtime_type or "openclaw")
            url_online[url] = health.get("online", False)

    changed = False
    for a in agents:
        url = a.runtime_url
        is_online = bool(url and url_online.get(url, False))

        # Resolve correct status
        new_status = _resolve_agent_status(a, is_online, db)
        if a.status != new_status:
            a.status = new_status
            changed = True

        if not url:
            continue

        if is_online:
            a.last_heartbeat = now
            # Pull live costs
            agent_name = a.runtime_agent_name or (a.profile.name if a.profile else a.name)
            rt = a.runtime_type or "openclaw"
            gw_token = a.runtime_gateway_token or ""
            costs = runtime_client.get_costs(url, gw_token, agent_name, rt)
            if costs and costs.get("estimated_cost_usd"):
                live_costs[a.id] = costs["estimated_cost_usd"]
            # Sync model from runtime sessions if agent has no model set
            if not a.model and costs and costs.get("model"):
                a.model = costs["model"]
                changed = True

    if changed:
        db.commit()
    return live_costs


# ── Agents ───────────────────────────────────────────────────────────────

def list_agents(status: Optional[str] = None) -> list[dict]:
    with _session() as db:
        _sync_bots(db)
        agents = db.query(Agent).order_by(Agent.created_at.desc()).all()
        live_costs = _refresh_status(db, agents)
        if status:
            agents = [a for a in agents if a.status.value == status]
        return [_agent_to_dict(a, runtime_cost=live_costs.get(a.id)) for a in agents]


def get_agent(agent_id: str) -> dict | None:
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return None
        live_costs = _refresh_status(db, [a])
        return _agent_to_dict(a, runtime_cost=live_costs.get(a.id))


def create_agent(*, profile_id: str | None = None, name: str, executor_type: str = "http",
                 model: str = "", webhook_url: str = "", config_json: str | None = None,
                 runtime_id: str | None = None) -> dict:
    """Create an agent. AP-86: every agent has a 1:1 backing Profile (bot
    identity) sharing the same id. Runtime config + identity persist together.

    If `profile_id` is given, reuse it (link an existing bot profile to a
    new runtime). Otherwise create both the profile and the agent here.
    """
    from backend.models import Profile, Role
    with _session() as db:
        if profile_id:
            prof = db.get(Profile, profile_id)
            if not prof:
                return {"error": "profile not found"}
        else:
            # Create a bot profile to back this agent. Same id as the agent
            # so they're 1:1 at the schema level too.
            role_row = db.query(Role).filter(Role.name == "bot").first()
            if not role_row:
                return {"error": "bot role missing"}
            new_id = _new_id()
            prof = Profile(
                id=new_id, name=name, display_name=name,
                password_hash="", avatar_url="", webhook_url="",
                role_id=role_row.id,
                model=model,
                runtime_id=runtime_id,
            )
            db.add(prof)
            db.flush()
            profile_id = prof.id
        a = Agent(
            id=profile_id,  # 1:1 with profile
            profile_id=profile_id,
            name=name,
            executor_type=executor_type,
            model=model,
            webhook_url=webhook_url,
            config_json=config_json,
            runtime_id=runtime_id,
        )
        db.add(a)
        # Mirror runtime fields onto the profile (source of truth post-merge).
        prof.name = name
        prof.display_name = name
        prof.model = model
        prof.runtime_id = runtime_id
        db.commit()
        db.refresh(a)
        return _agent_to_dict(a)


# Fields that, when set via update_agent, must mirror onto the backing Profile
# (post-AP-86 merge, the profile holds the canonical runtime config).
_AGENT_TO_PROFILE_MIRROR = {
    "name", "model", "system_prompt", "personality", "runtime_id",
    "default_project_id", "mcp_servers", "webhook_url",
}


def update_agent(agent_id: str, **fields) -> dict | None:
    from backend.models import Profile
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return None
        # mcp_servers comes in as a list[str]; persist as JSON.
        if "mcp_servers" in fields and fields["mcp_servers"] is not None:
            fields["mcp_servers"] = json.dumps(list(fields["mcp_servers"]))
        for k, v in fields.items():
            if v is not None and hasattr(a, k):
                setattr(a, k, v)
        # Mirror runtime-relevant fields onto the linked profile so the
        # post-merge "agent IS the profile" view stays consistent.
        prof = db.get(Profile, a.profile_id) if a.profile_id else None
        if prof:
            for k, v in fields.items():
                if v is None or k not in _AGENT_TO_PROFILE_MIRROR:
                    continue
                if hasattr(prof, k):
                    setattr(prof, k, v)
        db.commit()
        db.refresh(a)
        return _agent_to_dict(a)


def list_agent_projects(agent_id: str) -> list[dict]:
    """AP-86: projects this agent is assigned to. After the bot↔agent merge,
    agent.id == profile.id, so we walk the profile's ProjectMember rows."""
    from backend.models import Profile, Project, ProjectMember
    with _session() as db:
        # agent.id == profile.id post-merge; fall back to profile_id for any
        # transitional rows where they still differ.
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return []
        pid = a.profile_id or a.id
        rows = (db.query(Project)
                  .join(ProjectMember, ProjectMember.project_id == Project.id)
                  .filter(ProjectMember.profile_id == pid)
                  .order_by(Project.name.asc())
                  .all())
        return [
            {
                "id": p.id,
                "name": p.name,
                "key_prefix": p.key_prefix or "",
                "repo_path": p.repo_path or "",
            }
            for p in rows
        ]


def list_mcp_servers(*, include_auto: bool = False) -> list[dict]:
    """Expose the MCP registry to the frontend's agent edit form. By
    default hides auto-injected servers — users can't toggle them."""
    from backend.forge.mcp_registry import list_servers
    return list_servers(include_auto=include_auto)


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


def reset_agent_status(agent_id: str) -> dict | None:
    """Force-reset agent status. Fails orphaned runs, unsticks BUSY."""
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return None
        now = datetime.now(timezone.utc)
        # Fail any orphaned RUNNING/PENDING runs
        orphaned = (db.query(Run)
                    .filter(Run.agent_id == a.id,
                            Run.status.in_([RunStatus.RUNNING, RunStatus.PENDING]))
                    .all())
        for r in orphaned:
            r.status = RunStatus.FAILED
            r.error = "Reset: orphaned run cleaned up"
            r.finished_at = now
            if r.started_at:
                r.duration_ms = int((now - _utc(r.started_at)).total_seconds() * 1000)
        # Reset agent status based on runtime health
        from backend.forge import runtime_client
        if a.runtime_url:
            health = runtime_client.check_health(a.runtime_url, a.runtime_type or "openclaw")
            a.status = AgentStatus.ONLINE if health.get("online") else AgentStatus.OFFLINE
        else:
            a.status = AgentStatus.OFFLINE
        a.last_heartbeat = now
        db.commit()
        db.refresh(a)
        return {**_agent_to_dict(a), "orphaned_runs_failed": len(orphaned)}


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
            r.duration_ms = int((now - _utc(r.started_at)).total_seconds() * 1000)
        # Update agent stats
        if r.agent:
            r.agent.status = AgentStatus.ONLINE
            r.agent.total_runs += 1
            r.agent.total_cost_usd += cost_usd

        # Notify human admins on failure. Successful runs are silent —
        # bumping a notification per success would be noise. Per-user
        # opt-in for success notifications is a future enhancement.
        if r.status == RunStatus.FAILED:
            agent_name = r.agent.name if r.agent else "agent"
            short_err = (error or "unknown error")[:140]
            _notify_admins(
                db,
                type_="forge.run.failed",
                title=f"{agent_name} run failed: {short_err}",
                link=f"/forge/runs/{run_id}",
            )
        db.commit()
        db.refresh(r)
        return _run_to_dict(r)


def _notify_admins(db, *, type_: str, title: str, link: str) -> None:
    """Insert a Notification row for every profile with role=admin.

    Used by the forge layer to alert humans about agent run events.
    Caller is responsible for committing the session.
    """
    from backend.models import Notification, Role
    admins = (
        db.query(Profile)
        .join(Role, Profile.role_id == Role.id)
        .filter(Role.name == "admin")
        .all()
    )
    for prof in admins:
        db.add(Notification(
            profile_id=prof.id,
            type=type_,
            title=title[:255],
            link=link[:255],
        ))


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

        forge_cost = db.query(func.sum(Run.cost_usd)).scalar() or 0.0
        total_input_tokens = db.query(func.sum(Run.input_tokens)).scalar() or 0
        total_output_tokens = db.query(func.sum(Run.output_tokens)).scalar() or 0

        # Pull live runtime costs for all agents with a runtime_url
        from backend.forge import runtime_client
        runtime_total = 0.0
        runtime_input = 0
        runtime_output = 0
        agents = db.query(Agent).filter(Agent.runtime_url.isnot(None), Agent.runtime_url != "").all()
        for a in agents:
            agent_name = a.runtime_agent_name or (a.profile.name if a.profile else a.name)
            costs = runtime_client.get_costs(
                a.runtime_url, a.runtime_gateway_token or "",
                agent_name, a.runtime_type or "openclaw",
            )
            if costs:
                runtime_total += costs.get("estimated_cost_usd", 0) or 0
                runtime_input += costs.get("total_input_tokens", 0) or 0
                runtime_output += costs.get("total_output_tokens", 0) or 0

        total_cost = forge_cost + runtime_total
        total_input_tokens += runtime_input
        total_output_tokens += runtime_output

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


# ── Messages ────────────────────────────────────────────────────────────

def list_messages(agent_id: str, *, run_id: str | None = None,
                  limit: int = 100, offset: int = 0) -> list[dict]:
    with _session() as db:
        q = db.query(AgentMessage).filter(AgentMessage.agent_id == agent_id)
        if run_id:
            q = q.filter(AgentMessage.run_id == run_id)
        msgs = q.order_by(AgentMessage.created_at.asc()).offset(offset).limit(limit).all()
        return [_message_to_dict(m) for m in msgs]


def create_message(*, agent_id: str, role: str, content: str,
                   run_id: str | None = None, tool_name: str | None = None,
                   tool_input: str | None = None, tool_output: str | None = None,
                   input_tokens: int = 0, output_tokens: int = 0,
                   cost_usd: float = 0.0, model_used: str = "") -> dict:
    with _session() as db:
        m = AgentMessage(
            agent_id=agent_id,
            run_id=run_id,
            role=MessageRole(role),
            content=content,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            model_used=model_used,
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        return _message_to_dict(m)


# ── Webhook Logs ────────────────────────────────────────────────────────

def list_webhook_logs(agent_id: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
    with _session() as db:
        logs = (db.query(WebhookLog)
                .filter(WebhookLog.agent_id == agent_id)
                .order_by(WebhookLog.created_at.desc())
                .offset(offset).limit(limit).all())
        return [_webhook_log_to_dict(w) for w in logs]


def create_webhook_log(*, agent_id: str, direction: str = "outbound",
                       url: str = "", event: str = "", payload: str | None = None,
                       status_code: int | None = None, response_body: str | None = None,
                       success: bool = True, duration_ms: int | None = None) -> dict:
    with _session() as db:
        w = WebhookLog(
            agent_id=agent_id, direction=direction, url=url, event=event,
            payload=payload, status_code=status_code, response_body=response_body,
            success=success, duration_ms=duration_ms,
        )
        db.add(w)
        db.commit()
        db.refresh(w)
        return _webhook_log_to_dict(w)


# ── Schedule ────────────────────────────────────────────────────────────

def update_schedule(agent_id: str, *, start: str | None = None, end: str | None = None,
                    tz: str | None = None, days: str | None = None,
                    enabled: bool | None = None) -> dict | None:
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return None
        if start is not None:
            a.schedule_start = start
        if end is not None:
            a.schedule_end = end
        if tz is not None:
            a.schedule_tz = tz
        if days is not None:
            a.schedule_days = days
        if enabled is not None:
            a.schedule_enabled = enabled
        db.commit()
        db.refresh(a)
        return _agent_to_dict(a)


# ── Cost Estimation ─────────────────────────────────────────────────────

# Pricing per 1M tokens (input, output) — updated periodically
MODEL_PRICING = {
    # Anthropic — Claude 4 family (4-5, 4-6, 4-7 generations).
    # 4-7 is the current generation as of 2026; older entries kept for
    # legacy agents whose model field still references prior model ids.
    "claude-opus-4-7":            {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-7":          {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-7":           {"input": 0.80, "output": 4.0},
    "claude-opus-4-6":            {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6":          {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-6":           {"input": 0.80, "output": 4.0},
    "claude-opus-4-5":            {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-5":          {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5":           {"input": 0.80, "output": 4.0},
    # Legacy / dated SKUs
    "claude-opus-4-20250514":     {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-20250514":   {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5-20251001":  {"input": 0.80, "output": 4.0},
    "claude-3-5-sonnet-20241022": {"input": 3.0,  "output": 15.0},
    "claude-3-5-haiku-20241022":  {"input": 0.80, "output": 4.0},
    # OpenAI
    "gpt-4o":                     {"input": 2.50, "output": 10.0},
    "gpt-4o-mini":                {"input": 0.15, "output": 0.60},
    "gpt-4-turbo":                {"input": 10.0, "output": 30.0},
    "o3":                         {"input": 2.0,  "output": 8.0},
    "o3-mini":                    {"input": 1.10, "output": 4.40},
    # Google Gemini
    "google/gemini-2.5-pro":                {"input": 1.25, "output": 10.0},
    "google/gemini-2.5-flash":              {"input": 0.15, "output": 0.60},
    "google/gemini-3-flash-preview":        {"input": 0.15, "output": 0.60},
    "google/gemini-3.1-pro-preview":        {"input": 1.25, "output": 10.0},
    "google/gemini-3.1-flash-lite-preview": {"input": 0.075, "output": 0.30},
    "gemini-3.1-pro-preview":               {"input": 1.25, "output": 10.0},
    "gemini-3-flash-preview":               {"input": 0.15, "output": 0.60},
    "gemini-3.1-flash-lite-preview":        {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro":                       {"input": 1.25, "output": 10.0},
    "gemini-2.5-flash":                     {"input": 0.15, "output": 0.60},
}


def _resolve_model_pricing(model: str) -> dict | None:
    """Find pricing for a model, handling prefix/suffix and google/ prefix variants."""
    if not model:
        return None
    # Exact match
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    # Try with google/ prefix
    if not model.startswith("google/") and f"google/{model}" in MODEL_PRICING:
        return MODEL_PRICING[f"google/{model}"]
    # Try without google/ prefix
    if model.startswith("google/") and model[7:] in MODEL_PRICING:
        return MODEL_PRICING[model[7:]]
    # Prefix match
    for key, val in MODEL_PRICING.items():
        if model.startswith(key.rsplit("-", 1)[0]):
            return val
    return None


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> dict:
    pricing = _resolve_model_pricing(model)
    if not pricing:
        return {"input_cost": 0, "output_cost": 0, "total_cost": 0, "model": model, "pricing_found": False}
    input_cost = input_tokens / 1_000_000 * pricing["input"]
    output_cost = output_tokens / 1_000_000 * pricing["output"]
    return {
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(input_cost + output_cost, 6),
        "model": model,
        "pricing_found": True,
        "rates": pricing,
    }


def get_agent_cost_breakdown(agent_id: str) -> dict:
    """Per-model cost breakdown for an agent."""
    with _session() as db:
        runs = db.query(Run).filter(Run.agent_id == agent_id).all()
        by_model = {}
        total_input = 0
        total_output = 0
        total_cost = 0.0
        for r in runs:
            model = r.model_used or "unknown"
            if model not in by_model:
                by_model[model] = {"runs": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
            by_model[model]["runs"] += 1
            by_model[model]["input_tokens"] += r.input_tokens
            by_model[model]["output_tokens"] += r.output_tokens
            by_model[model]["cost_usd"] += r.cost_usd
            total_input += r.input_tokens
            total_output += r.output_tokens
            total_cost += r.cost_usd
        return {
            "agent_id": agent_id,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cost_usd": round(total_cost, 4),
            "by_model": by_model,
        }


def get_agent_involvement(agent_id: str) -> dict:
    """Per-(agent) summary of runs across projects — feeds get_my_involvement.

    Joins forge_runs → tasks → projects so each project gets a roll-up of
    run_count, last_active, and the tasks the agent has touched. Tokens
    and cost come straight off forge_runs aggregates.
    """
    from backend.models import Task, Project
    with _session() as db:
        runs = (db.query(Run)
                  .filter(Run.agent_id == agent_id)
                  .order_by(Run.created_at.desc())
                  .all())
        if not runs:
            return {
                "agent_id": agent_id,
                "total_runs": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost_usd": 0.0,
                "projects": [],
            }

        total_in = 0
        total_out = 0
        total_cost = 0.0
        # project_id -> {project_name, run_count, last_active, tasks: {task_id: {title, last_at}}}
        by_project: dict[str, dict] = {}

        for r in runs:
            total_in += r.input_tokens
            total_out += r.output_tokens
            total_cost += r.cost_usd

            # Resolve project — prefer the run's own project_id, fall back
            # to the task's project. Both can be null for free-form chat.
            project_id = r.project_id
            task_title = ""
            if r.task_id:
                task = db.get(Task, r.task_id)
                if task:
                    task_title = task.title or ""
                    if not project_id:
                        project_id = task.project_id

            if not project_id:
                continue  # skip free-form runs that aren't project-scoped

            bucket = by_project.setdefault(project_id, {
                "project_name": "",
                "run_count": 0,
                "last_active": None,
                "tasks": {},
            })
            bucket["run_count"] += 1
            bucket["last_active"] = max(
                bucket["last_active"] or r.created_at,
                r.created_at,
            )
            if r.task_id:
                t = bucket["tasks"].setdefault(r.task_id, {
                    "task_id": r.task_id,
                    "task_title": task_title,
                    "last_run_at": r.created_at,
                })
                if r.created_at > t["last_run_at"]:
                    t["last_run_at"] = r.created_at

        # Backfill project names in one pass
        for pid, bucket in by_project.items():
            proj = db.get(Project, pid)
            if proj:
                bucket["project_name"] = proj.name or ""

        projects_out = []
        for pid, bucket in sorted(
            by_project.items(),
            key=lambda kv: kv[1]["last_active"] or datetime.min,
            reverse=True,
        ):
            projects_out.append({
                "project_id": pid,
                "project_name": bucket["project_name"],
                "run_count": bucket["run_count"],
                "last_active": _iso(bucket["last_active"]),
                "tasks_touched": sorted(
                    [
                        {**t, "last_run_at": _iso(t["last_run_at"])}
                        for t in bucket["tasks"].values()
                    ],
                    key=lambda x: x["last_run_at"] or "",
                    reverse=True,
                ),
            })

        return {
            "agent_id": agent_id,
            "total_runs": len(runs),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_cost_usd": round(total_cost, 4),
            "projects": projects_out,
        }


def get_model_pricing() -> dict:
    """Return the pricing table so the frontend can estimate costs."""
    return MODEL_PRICING


# ── OpenClaw config (direct file access) ──────────────────────────────

import os
import json as _json

_OPENCLAW_CONFIG_PATH = os.environ.get(
    "FORGE_OPENCLAW_CONFIG",
    os.path.expanduser("~/.openclaw/openclaw.json"),
)


def _read_openclaw_config() -> dict:
    """Read openclaw.json directly from disk."""
    try:
        with open(_OPENCLAW_CONFIG_PATH, "r", encoding="utf-8") as f:
            return _json.load(f)
    except (FileNotFoundError, _json.JSONDecodeError):
        return {}


def _write_openclaw_config(cfg: dict) -> bool:
    """Write openclaw.json back to disk."""
    try:
        with open(_OPENCLAW_CONFIG_PATH, "w", encoding="utf-8") as f:
            _json.dump(cfg, f, indent=4)
        return True
    except Exception:
        return False


def get_openclaw_models() -> dict:
    """Return available models and per-agent model assignments from OpenClaw config."""
    cfg = _read_openclaw_config()
    agents_cfg = cfg.get("agents", {})
    defaults = agents_cfg.get("defaults", {})

    default_model = defaults.get("model", {}).get("primary", "")
    available = []
    for model_id, meta in defaults.get("models", {}).items():
        available.append({
            "id": model_id,
            "alias": meta.get("alias", ""),
        })

    agent_models = {}
    for a in agents_cfg.get("list", []):
        agent_models[a["id"]] = a.get("model", default_model) or default_model

    # Also include models from pricing table that aren't in OpenClaw
    pricing_models = [{"id": m, "alias": ""} for m in MODEL_PRICING
                      if not any(av["id"] == m for av in available)]

    return {
        "default_model": default_model,
        "openclaw_models": available,
        "pricing_models": pricing_models,
        "agent_models": agent_models,
        "config_path": _OPENCLAW_CONFIG_PATH,
    }


def set_openclaw_agent_model(agent_name: str, model: str) -> dict:
    """Update an agent's model in openclaw.json and in Forge DB."""
    cfg = _read_openclaw_config()
    agents_cfg = cfg.get("agents", {})
    agent_list = agents_cfg.get("list", [])

    updated = False
    for a in agent_list:
        if a["id"] == agent_name:
            a["model"] = model
            updated = True
            break

    if not updated:
        return {"success": False, "error": f"Agent '{agent_name}' not found in openclaw.json"}

    if not _write_openclaw_config(cfg):
        return {"success": False, "error": "Failed to write openclaw.json"}

    # Also update Forge DB
    with _session() as db:
        forge_agent = (db.query(Agent)
                       .filter((Agent.runtime_agent_name == agent_name) |
                               (Agent.name == agent_name))
                       .first())
        if forge_agent:
            forge_agent.model = model
            db.commit()

    return {"success": True, "agent": agent_name, "model": model}


# ── Runtime (adapter-based, pull only) ─────────────────────────────────

def _agent_runtime(a: Agent) -> tuple[str, str, str, str]:
    """Extract runtime config from an agent → (url, gw_token, hooks_token, agent_name)."""
    return (
        a.runtime_url or "http://127.0.0.1:18789",
        a.runtime_gateway_token or "",
        a.runtime_hooks_token or "",
        a.runtime_agent_name or (a.profile.name if a.profile else a.name),
    )


def get_runtime_status(agent_id: str) -> dict:
    """Pull live status from the agent's runtime via adapter."""
    from backend.forge import runtime_client
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return {"online": False, "error": "Agent not found"}

        url, gw_token, _, agent_name = _agent_runtime(a)
        rt = a.runtime_type or "openclaw"

        health = runtime_client.check_health(url, rt)
        sessions = runtime_client.get_sessions(url, gw_token, agent_name, rt)
        is_online = health.get("online", False)

        # Update status using shared resolver
        new_status = _resolve_agent_status(a, is_online, db)
        if a.status != new_status:
            a.status = new_status
        if is_online:
            a.last_heartbeat = datetime.now(timezone.utc)
        db.commit()

        return {
            "online": is_online,
            "health": health,
            "sessions": sessions,
            "model": a.model or "",
            "runtime_type": rt,
            "latency_ms": health.get("latency_ms"),
        }


def get_runtime_sessions(agent_id: str) -> dict:
    """Pull live sessions + activity from the agent's runtime."""
    from backend.forge import runtime_client
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return {"error": "Agent not found"}
        url, gw_token, _, agent_name = _agent_runtime(a)
        rt = a.runtime_type or "openclaw"
        return {
            "sessions": runtime_client.get_sessions(url, gw_token, agent_name, rt),
            "activity": runtime_client.get_activity(url, gw_token, agent_name, runtime_type=rt),
        }


def get_runtime_costs(agent_id: str) -> dict:
    """Pull cost/usage data from the agent's runtime."""
    from backend.forge import runtime_client
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return {"error": "Agent not found"}
        url, gw_token, _, agent_name = _agent_runtime(a)
        rt = a.runtime_type or "openclaw"
        runtime_costs = runtime_client.get_costs(url, gw_token, agent_name, rt)
        # Merge with Forge's own tracked costs
        forge_costs = get_agent_cost_breakdown(agent_id)
        return {
            "runtime": runtime_costs,
            "forge": forge_costs,
        }


def get_openclaw_overview() -> dict:
    """Overview: health of all configured runtimes."""
    from backend.forge import runtime_client
    with _session() as db:
        agents = db.query(Agent).filter(Agent.runtime_url != "").all()
        seen: dict[str, dict] = {}
        for a in agents:
            url = a.runtime_url
            if url not in seen:
                rt = a.runtime_type or "openclaw"
                seen[url] = {
                    "url": url,
                    "runtime_type": rt,
                    "health": runtime_client.check_health(url, rt),
                    "agents": [],
                }
            seen[url]["agents"].append({
                "id": a.id,
                "name": a.name,
                "runtime_agent_name": a.runtime_agent_name,
                "status": a.status.value,
                "model": a.model or "",
            })
        return {"runtimes": list(seen.values())}


def sync_openclaw_agents() -> list[dict]:
    """Sync runtime data into forge agents via adapter pull."""
    from backend.forge import runtime_client
    with _session() as db:
        _sync_bots(db)
        forge_agents = db.query(Agent).all()
        now = datetime.now(timezone.utc)

        for a in forge_agents:
            if not a.runtime_url:
                continue
            url, gw_token, _, agent_name = _agent_runtime(a)
            rt = a.runtime_type or "openclaw"

            health = runtime_client.check_health(url, rt)
            is_online = health.get("online", False)

            new_status = _resolve_agent_status(a, is_online, db)
            if a.status != new_status:
                a.status = new_status
            if is_online:
                a.last_heartbeat = now
                # Pull model from runtime sessions
                costs = runtime_client.get_costs(url, gw_token, agent_name, rt)
                if costs and costs.get("model") and not a.model:
                    a.model = costs["model"]

        db.commit()
        return [_agent_to_dict(a) for a in forge_agents]


def dispatch_trigger(agent_id: str, prompt: str, *,
                     run_id: str | None = None, kind: str = "chat",
                     repo_path: str = "", conventions_md: str = "",
                     mcp_config_json: str = "", env_extra: dict | None = None,
                     run_token: str = "",
                     user_context: dict | None = None) -> dict:
    """Single rail for invoking an agent.

    Saves the user prompt as an AgentMessage tagged with a fresh `trace_id`,
    then fires one WS frame to the agent's bound daemon. Used for chat,
    scheduled run steps, and (later) comments / webhooks / mentions.

    `kind` is a label for audit/logging only — the daemon does not branch on it.
    `run_id` attaches the trigger to a Run when the work is part of a workflow
    (cron, task assignment); for free-floating chat it stays None.

    Run-context bundle (used by Phase D's daemon materializer; chat triggers
    pass empty values and the daemon falls back to its existing behavior):
    - repo_path: filesystem path the daemon will symlink into the workdir
    - conventions_md: runtime-agnostic markdown the daemon writes to
      .agentira/CONVENTIONS.md
    - mcp_config_json: serialized {"mcpServers": {...}} for --mcp-config
    - env_extra: dict of env vars to inject (AGENTIRA_RUN_ID, etc.)
    - run_token: per-run uuid the agent uses to authenticate finish_run
    """
    import asyncio
    import uuid
    from backend.forge.ws_dispatch import hub

    trace_id = uuid.uuid4().hex[:12]

    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a or not a.runtime_id:
            return {"error": "Agent has no bound runtime"}
        runtime = db.get(ForgeRuntime, a.runtime_id)
        if not runtime:
            return {"error": "Runtime not found"}

        # Persist the user message tagged with trace_id (and run_id when present)
        db.add(AgentMessage(
            agent_id=a.id,
            run_id=run_id,
            trace_id=trace_id,
            kind=kind,
            role=MessageRole.USER,
            content=prompt,
        ))
        db.commit()

        runtime_id = a.runtime_id
        provider = runtime.provider
        gateway_url = runtime.gateway_url or ""
        gateway_token = runtime.gateway_token or ""
        model = a.model or ""
        system_prompt = a.system_prompt or ""
        agent_name = a.runtime_agent_name or (a.profile.name if a.profile else a.name)

    # If this trigger belongs to a Run (cron, scheduled task, …), flip the
    # run state to RUNNING before dispatching. complete_trigger will close
    # it out at the daemon side.
    if run_id:
        start_run(run_id)

    # Bundle user_context into env_extra so daemon-side code that already
    # consumes env_extra (per AP-51's dispatch shape) picks it up without
    # a new field on the WS frame. The daemon JSON-decodes it.
    env_extra_combined = dict(env_extra or {})
    if user_context:
        env_extra_combined["AGENTIRA_USER_CONTEXT_JSON"] = json.dumps(user_context)

    asyncio.ensure_future(hub.dispatch_trigger(
        trace_id=trace_id,
        runtime_id=runtime_id,
        agent_id=agent_id,
        run_id=run_id or "",
        kind=kind,
        prompt=prompt,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        agent_name=agent_name,
        gateway_url=gateway_url,
        gateway_token=gateway_token,
        repo_path=repo_path,
        conventions_md=conventions_md,
        mcp_config_json=mcp_config_json,
        env_extra=env_extra_combined,
        run_token=run_token,
    ))
    return {"ok": True, "trace_id": trace_id, "run_id": run_id}


def schedule_task_run(*, task_id: str, agent_id: str) -> dict:
    """Kick off a Run for a task with the chosen agent.

    Builds the prompt from the task's title + description + DoD items
    (the work-defining content the human authored), then dispatches a
    trigger of kind=run_step with the new run_id. The agent's
    system_prompt rides on the trigger frame so the runtime sees it.

    Assembles the run-context bundle (project repo_path + conventions_md,
    agent's MCP toolkit, per-run token + env vars) and ships it on the
    dispatch frame. Phase D wires the daemon to consume it; until then
    the daemon ignores the extra fields and chat continues to work.
    """
    import json as _json
    import uuid
    from backend.models import Task, Project
    from backend.forge.mcp_registry import build_mcp_config

    with _session() as db:
        task = db.get(Task, task_id)
        if not task:
            return {"error": "Task not found"}
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            return {"error": "Agent not found"}
        if not agent.runtime_id:
            return {"error": "Agent has no bound runtime"}

        task_title = task.title or ""
        task_description = task.description or ""
        project_id = task.project_id
        dod_text = ""
        if task.dod_items:
            try:
                items = json.loads(task.dod_items)
                if isinstance(items, list) and items:
                    dod_text = "\n".join(
                        f"- [{'x' if it.get('checked') else ' '}] {it.get('text','')}"
                        for it in items if isinstance(it, dict)
                    )
            except Exception:
                pass

        # Project run-context — empty strings if unset; daemon falls back
        # to its existing cwd-and-no-conventions behavior in that case.
        project = db.get(Project, project_id) if project_id else None
        repo_path = (project.repo_path or "") if project else ""
        conventions_md = (project.conventions_md or "") if project else ""

        # Agent toolkit — list of opt-in MCP server names.
        agent_mcp_servers: list[str] = []
        if agent.mcp_servers:
            try:
                parsed = _json.loads(agent.mcp_servers)
                if isinstance(parsed, list):
                    agent_mcp_servers = [str(s) for s in parsed]
            except Exception:
                pass

    # Compose the prompt outside the session — clean, deterministic.
    parts = [f"# Task: {task_title}"]
    if task_description:
        parts.append("\n## Description\n" + task_description)
    if dod_text:
        parts.append("\n## Definition of Done\n" + dod_text)
    parts.append("\nWork on this task.")
    # Stash run_id placeholder; we substitute the real one once it's created
    # (the prompt is composed before create_run runs). The literal {run_id}
    # is replaced below.
    parts.append(
        "\nWhen you finish, call mcp__agentira__finish_run with:\n"
        "  - run_id: \"{run_id}\"\n"
        "  - outcome: one of \"succeeded\" | \"blocked\" | \"needs_input\" | \"failed\"\n"
        "  - summary: one paragraph describing what changed (or what's blocking).\n"
        "Use \"blocked\" when you can't proceed without external input "
        "(missing credentials, ambiguous spec, broken dependency)."
    )
    prompt_template = "\n".join(parts)

    # Create the Run row first; dispatch_trigger will flip it to RUNNING.
    run = create_run(
        agent_id=agent_id,
        task_id=task_id,
        project_id=project_id,
        trigger_event="task.scheduled",
        model_used=agent.model or "",
    )
    run_id = run["id"]

    # Substitute the real run_id into the finish_run instructions now that
    # the run row exists.
    prompt = prompt_template.replace("{run_id}", run_id)

    # Build the MCP config (auto servers + agent's picks; memory scoped per
    # (agent, project)). Serialize to JSON so it rides on the WS frame as a
    # single string — the daemon writes it to a tmpfile for --mcp-config.
    mcp_config = build_mcp_config(
        agent_mcp_servers=agent_mcp_servers,
        agent_id=agent_id,
        project_id=project_id,
    )
    mcp_config_json = _json.dumps(mcp_config)

    # Per-run token — used by finish_run (Phase E) to scope the agent's
    # outcome to this specific run. Generated here, rides on the frame as
    # AGENTIRA_RUN_TOKEN. Not persisted yet; tighten with a proper token
    # store when per-run scoping moves out of "trust the agent" mode.
    run_token = uuid.uuid4().hex

    env_extra = {
        "AGENTIRA_RUN_ID": run_id,
        "AGENTIRA_TASK_ID": task_id,
        "AGENTIRA_PROJECT_ID": project_id or "",
        "AGENTIRA_AGENT_ID": agent_id,
        "AGENTIRA_RUN_TOKEN": run_token,
    }

    result = dispatch_trigger(
        agent_id, prompt,
        run_id=run_id, kind="run_step",
        repo_path=repo_path,
        conventions_md=conventions_md,
        mcp_config_json=mcp_config_json,
        env_extra=env_extra,
        run_token=run_token,
    )
    return {**result, "run_id": run_id, "task_id": task_id}


def _signal_run(run_id: str, frame_type: str, target_status: "RunStatus | None") -> dict:
    """Shared body for pause/resume — both fire a WS frame to the daemon
    and optionally flip the Run state. Cancel uses a different path
    because it's terminal and races the daemon's complete event."""
    import asyncio
    from backend.forge.ws_dispatch import hub
    with _session() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            return {"error": "Run not found"}
        if run.status not in (RunStatus.RUNNING, RunStatus.PAUSED, RunStatus.PENDING):
            return {"error": f"Run is {run.status.value}; cannot {frame_type}"}
        agent = db.get(Agent, run.agent_id)
        runtime_id = agent.runtime_id if agent else None
        last_msg = (db.query(AgentMessage)
                    .filter(AgentMessage.run_id == run_id)
                    .order_by(AgentMessage.created_at.desc())
                    .first())
        trace_id = last_msg.trace_id if last_msg else ""
        if target_status is not None:
            run.status = target_status
            db.commit()
            db.refresh(run)
        run_dict = _run_to_dict(run)

    if runtime_id:
        try:
            asyncio.ensure_future(hub.dispatch_signal(
                runtime_id=runtime_id,
                signal=frame_type,
                trace_id=trace_id,
                run_id=run_id,
            ))
        except Exception:
            pass
    return {"ok": True, "run": run_dict}


def pause_run(run_id: str) -> dict:
    """Pause a running CLI subprocess (SIGSTOP). Best-effort: openclaw
    HTTP runs aren't pausable (the request completes naturally). Long
    pauses can break the LLM API timeout — use cancel + resume-by-session
    for anything beyond a few minutes."""
    return _signal_run(run_id, "pause", RunStatus.PAUSED)


def resume_run(run_id: str) -> dict:
    """Resume a paused CLI subprocess (SIGCONT)."""
    return _signal_run(run_id, "resume", RunStatus.RUNNING)


def cancel_run(run_id: str) -> dict:
    """Cancel a pending or running Run.

    Resolves the agent's runtime, fires a cancel WS frame so the daemon
    kills the in-flight subprocess (if any), and immediately marks the
    Run as cancelled in the DB. The daemon will also post a complete
    when it sees the kill, but we don't wait for that — the user
    pressing cancel needs immediate feedback.
    """
    import asyncio
    from backend.forge.ws_dispatch import hub
    with _session() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            return {"error": "Run not found"}
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            return {"error": f"Run already {run.status.value}"}
        agent = db.get(Agent, run.agent_id)
        runtime_id = agent.runtime_id if agent else None

        # Look up the latest trace_id for this run so the daemon can match.
        last_msg = (db.query(AgentMessage)
                    .filter(AgentMessage.run_id == run_id)
                    .order_by(AgentMessage.created_at.desc())
                    .first())
        trace_id = last_msg.trace_id if last_msg else ""

        # Mark run cancelled now — don't make the user wait for the daemon's
        # complete-event round-trip. complete_trigger from the daemon will
        # see the run already cancelled and skip the state flip.
        now = datetime.now(timezone.utc)
        run.status = RunStatus.CANCELLED
        run.finished_at = now
        run.error = "Cancelled by user."
        if run.started_at:
            run.duration_ms = int((now - _utc(run.started_at)).total_seconds() * 1000)
        if run.agent and run.agent.status == AgentStatus.BUSY:
            run.agent.status = AgentStatus.ONLINE
        db.commit()
        db.refresh(run)
        run_dict = _run_to_dict(run)

    # Best-effort cancel signal to the daemon
    if runtime_id:
        try:
            asyncio.ensure_future(hub.dispatch_cancel(
                runtime_id=runtime_id, trace_id=trace_id, run_id=run_id,
            ))
        except Exception as exc:
            # WS dispatch is best-effort — the run is already marked cancelled.
            pass

    return {"ok": True, "run": run_dict}


def finish_run(run_id: str, *, outcome: str, summary: str = "",
               run_token: str = "") -> dict:
    """Agent-declared semantic completion (called from finish_run MCP tool).

    Sets Run.outcome (the semantic verdict — succeeded / blocked / needs_input
    / failed) and Run.summary (one-paragraph human-readable result).

    `outcome` validation rejects unknown values so a typo doesn't silently
    leave the field unset. The MCP tool surfaces the error to the agent.

    `run_token` is plumbed through for future per-run scoping; today we
    trust the run_id arg (Phase G hardening). When implemented it will
    cross-check run_token against the dispatch frame's AGENTIRA_RUN_TOKEN.

    Idempotent: re-calling with the same outcome is a no-op. Calling
    after a run has been cancelled/failed terminally still updates
    outcome/summary so the agent's last-word verdict is preserved.
    """
    try:
        outcome_enum = RunOutcome(outcome)
    except ValueError:
        valid = [o.value for o in RunOutcome]
        return {"ok": False, "error": f"Invalid outcome '{outcome}'. Must be one of: {valid}"}

    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return {"ok": False, "error": "Run not found"}
        r.outcome = outcome_enum
        if summary:
            r.summary = summary
        db.commit()
        db.refresh(r)
        return {"ok": True, "run": _run_to_dict(r)}


def list_runs_for_task(task_id: str) -> list[dict]:
    """Return all runs scheduled against a task, newest first."""
    with _session() as db:
        runs = (db.query(Run)
                .filter(Run.task_id == task_id)
                .order_by(Run.created_at.desc())
                .all())
        return [_run_to_dict(r) for r in runs]


def append_trigger_events(agent_id: str, *, trace_id: str, run_id: str | None,
                          events: list) -> dict:
    """Store streamed events from the daemon as AgentMessage records.

    One sink for every trigger kind (chat, run_step, …). Messages are tagged
    with `trace_id` so the UI can group a turn, and with `run_id` when present
    so run-detail views still query by run.
    """
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return {"ok": False, "error": "Agent not found"}
        for evt in events:
            evt_type = evt.get("type", "")
            if evt_type == "text":
                content = evt.get("text", "")
                if not content:
                    continue
                role = MessageRole.ASSISTANT
                tool_name = None
            elif evt_type == "tool_use":
                role = MessageRole.TOOL
                content = evt.get("tool", "")
                tool_name = evt.get("tool")
            elif evt_type == "tool_result":
                role = MessageRole.TOOL
                content = evt.get("output", "")
                tool_name = evt.get("tool")
            else:
                continue
            db.add(AgentMessage(
                agent_id=agent_id,
                run_id=run_id,
                trace_id=trace_id,
                role=role,
                content=content,
                tool_name=tool_name,
                tool_input=json.dumps(evt.get("input")) if evt.get("input") is not None else None,
                tool_output=evt.get("output") if evt_type == "tool_result" else None,
                model_used=evt.get("model", ""),
            ))
        db.commit()
        return {"ok": True, "count": len(events)}


def complete_trigger(agent_id: str, *, trace_id: str, run_id: str | None,
                     success: bool, input_tokens: int = 0, output_tokens: int = 0,
                     error: str | None = None,
                     diff_stat: str = "", diff: str = "") -> dict:
    """Finalize a trigger. Updates the Run if `run_id` is set; for chat
    triggers we still surface the failure as a system-role message on
    the agent so the chat UI shows what actually went wrong instead of
    sitting silent forever."""
    logger_msg = (f"complete_trigger trace={trace_id} agent={agent_id} "
                  f"run={run_id or '-'} ok={success} tokens={input_tokens}/{output_tokens}")
    if run_id:
        complete_run(
            run_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error=error if not success else None,
        )
        # Default outcome + persist diff. We do these together so we only
        # round-trip to the DB once; the agent's explicit outcome (if any)
        # is set first by finish_run and we don't clobber it here.
        with _session() as db:
            r = db.query(Run).filter(Run.id == run_id).first()
            if r:
                if r.outcome is None:
                    r.outcome = RunOutcome.SUCCEEDED if success else RunOutcome.FAILED
                if diff_stat:
                    r.diff_stat = diff_stat
                if diff:
                    r.diff = diff
                db.commit()

    # Failure surfacing — the daemon already logs server-side, but the
    # human in the UI only sees what's in the chat thread. Drop a
    # system-role message tagged with this trace so the existing chat
    # poll picks it up.
    if not success and error:
        with _session() as db:
            db.add(AgentMessage(
                agent_id=agent_id,
                run_id=run_id,
                trace_id=trace_id,
                role=MessageRole.SYSTEM,
                content=f"⚠ Agent execution failed: {error[:600]}",
            ))
            db.commit()

    return {"ok": True, "trace_id": trace_id, "logged": logger_msg}


def get_trigger_events(trace_id: str) -> list[dict]:
    """Return all messages tagged with this trace_id, ordered by creation time."""
    with _session() as db:
        msgs = (db.query(AgentMessage)
                .filter(AgentMessage.trace_id == trace_id)
                .order_by(AgentMessage.created_at.asc())
                .all())
        return [_message_to_dict(m) for m in msgs]


def get_run_events(run_id: str) -> list[dict]:
    """Return messages tagged with this run_id (covers any number of triggers
    that fired against the run), ordered by creation time."""
    with _session() as db:
        msgs = (db.query(AgentMessage)
                .filter(AgentMessage.run_id == run_id)
                .order_by(AgentMessage.created_at.asc())
                .all())
        return [_message_to_dict(m) for m in msgs]


def send_runtime_message(
    agent_id: str,
    *,
    content: str,
    run_id: str | None = None,
    user_context: dict | None = None,
) -> dict:
    """Send a message to the agent via runtime adapter, log both sides.

    `user_context` (AP-76): per-call hint about where the user is. If it
    carries a `project_id`, we resolve the project's repo_path / conventions
    / mcp_config and forward them on the dispatch frame so the daemon can
    spawn the runtime in the right cwd. The whole dict is also forwarded
    so the daemon can render a synthetic system message ("you are helping
    the user who is currently viewing …").
    """
    from backend.forge import runtime_client
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return {"error": "Agent not found"}
        if a.runtime_id:
            # Resolve project context from user_context's project_id (if any).
            # No project_id → free-form chat, no cwd, no MCP project tools.
            repo_path = ""
            conventions_md = ""
            mcp_config_json = ""
            ctx = user_context if isinstance(user_context, dict) else {}
            project_id = ctx.get("project_id")
            if project_id:
                from backend.forge.mcp_registry import build_mcp_config
                from backend.models import Project
                proj = db.get(Project, project_id)
                if proj:
                    repo_path = proj.repo_path or ""
                    conventions_md = proj.conventions_md or ""
                    cfg = build_mcp_config(a, project_id)
                    mcp_config_json = json.dumps(cfg) if cfg else ""
            return dispatch_trigger(
                agent_id, content, run_id=run_id, kind="chat",
                repo_path=repo_path,
                conventions_md=conventions_md,
                mcp_config_json=mcp_config_json,
                user_context=user_context,
            )

        url, gw_token, _, agent_name = _agent_runtime(a)
        rt = a.runtime_type or "openclaw"

        # Log the outgoing user message
        user_msg = AgentMessage(
            agent_id=a.id, run_id=run_id,
            role=MessageRole.USER, content=content,
            model_used=a.model or "",
        )
        db.add(user_msg)
        db.commit()

        # Build message history for context
        recent = (db.query(AgentMessage)
                  .filter(AgentMessage.agent_id == a.id)
                  .order_by(AgentMessage.created_at.desc())
                  .limit(20).all())
        recent.reverse()

        messages = []
        if a.system_prompt:
            messages.append({"role": "system", "content": a.system_prompt})
        for m in recent:
            messages.append({"role": m.role.value, "content": m.content})

        # Send via adapter
        result = runtime_client.send_chat(url, gw_token, agent_name, messages, rt)

        if "_error" in result:
            # Log failed attempt
            wh = WebhookLog(
                agent_id=a.id, direction="outbound",
                url=f"{url}/v1/chat/completions",
                event="forge.chat",
                payload=json.dumps({"content": content[:500]}),
                status_code=500, success=False,
                duration_ms=result.get("_latency_ms"),
                response_body=result["_error"][:500],
            )
            db.add(wh)
            db.commit()
            return {"success": False, "error": result["_error"], "duration_ms": result.get("_latency_ms")}

        # Calculate cost — use API value or estimate from tokens
        cost_usd = result.get("cost_usd", 0.0)
        in_tok = result.get("input_tokens", 0)
        out_tok = result.get("output_tokens", 0)
        # Use agent's configured model for pricing (API returns "openclaw:agent" which isn't in pricing table)
        model_used = a.model or result.get("model", "")
        if not cost_usd and (in_tok or out_tok):
            est = estimate_cost(model_used, in_tok, out_tok)
            cost_usd = est.get("total_cost", 0.0)

        # Log the assistant response
        assistant_msg = AgentMessage(
            agent_id=a.id, run_id=run_id,
            role=MessageRole.ASSISTANT,
            content=result.get("content", ""),
            model_used=model_used,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost_usd,
        )
        db.add(assistant_msg)

        # Log webhook delivery
        wh = WebhookLog(
            agent_id=a.id, direction="outbound",
            url=f"{url}/v1/chat/completions",
            event="forge.chat",
            payload=json.dumps({"content": content[:500]}),
            status_code=200, success=True,
            duration_ms=result.get("_latency_ms"),
            response_body=json.dumps({
                "content": result.get("content", "")[:500],
                "model": result.get("model", ""),
                "tokens": result.get("input_tokens", 0) + result.get("output_tokens", 0),
            }),
        )
        db.add(wh)

        # Update agent cost stats
        a.total_cost_usd += cost_usd
        db.commit()

        return {
            "success": True,
            "content": result.get("content", ""),
            "model": model_used,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": cost_usd,
            "duration_ms": result.get("_latency_ms"),
        }


