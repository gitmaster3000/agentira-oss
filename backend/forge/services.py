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
    Agent, Run, AgentMessage, WebhookLog, Conversation,
    AgentStatus, RunStatus, RunOutcome, MessageRole,
    ForgeRuntime, RuntimeStatus,
    _new_id,
)

import asyncio as _asyncio
import logging as _logging

_dispatch_logger = _logging.getLogger("agentira.forge.dispatch")

# The backend's main asyncio loop. WS objects in `hub` are bound to it.
# Captured at app startup (rest_api.startup) and refreshed whenever a
# dispatch runs inside a request. Background threads (the AP-80 Conductor
# tick runs in APScheduler's threadpool) have NO event loop of their own,
# so they must marshal dispatch coroutines onto THIS loop.
_MAIN_LOOP: "_asyncio.AbstractEventLoop | None" = None


def set_main_loop(loop) -> None:
    """Record the backend's main event loop (called from app startup)."""
    global _MAIN_LOOP
    _MAIN_LOOP = loop


def _dispatch_coro(coro) -> None:
    """Schedule a hub dispatch coroutine from any thread.

    Three cases, in order:
      1. Async request context — a loop is running in this thread:
         attach the coroutine to it.
      2. Background thread (Conductor / APScheduler tick) — no loop here,
         but the backend's main loop was captured at startup: marshal
         onto it via run_coroutine_threadsafe (the hub's WS sockets live
         there).
      3. No app loop at all (unit tests, or pre-startup) — schedule on
         this thread's event loop if one is set; the caller pumps it.
         Only if there is genuinely no loop do we drop + log.
    """
    global _MAIN_LOOP
    # 1. Running loop in this thread.
    try:
        loop = _asyncio.get_running_loop()
        _MAIN_LOOP = loop
        loop.create_task(coro)
        return
    except RuntimeError:
        pass  # no running loop in this thread
    # 2. Background thread → marshal onto the captured main loop.
    if _MAIN_LOOP is not None and _MAIN_LOOP.is_running():
        _asyncio.run_coroutine_threadsafe(coro, _MAIN_LOOP)
        return
    # 3. No app loop — schedule on this thread's set event loop (tests).
    try:
        _asyncio.ensure_future(coro)
    except RuntimeError:
        coro.close()
        _dispatch_logger.error(
            "dispatch dropped — no event loop available (main loop not captured)"
        )


# ── Agent home + worktree primitives ─────────────────────────────────────
#
# Every agent has a persistent home directory on the daemon's host.
# Default: ~/.agentira/agents/<id>/home/. Inside lives the agent's repo
# worktrees, memory MCP store, scratch notes. This is the agent's
# physical address — what gives session resume, sandbox boundaries, and
# diff capture a stable anchor.

def resolve_agent_home(agent) -> str:
    """Return the agent's home path as a TEMPLATE (with `~` unexpanded).

    Backend MUST NOT expanduser here — backend runs inside docker as
    `root` and `~` resolves to `/root`, but the daemon runs on the host
    where `~` is the real user. Sending `/root/...` to the daemon makes
    the path non-existent on the host and dispatch falls back to a
    different cwd, breaking claude --resume.

    Always return the template (e.g. `~/.agentira/agents/abc/home`);
    the daemon expands it.
    """
    explicit = None
    prof = getattr(agent, "profile", None)
    if prof is not None:
        explicit = getattr(prof, "home_path", None)
    if not explicit:
        explicit = getattr(agent, "home_path", None)
    if explicit:
        return explicit  # raw — daemon expands
    agent_id = getattr(agent, "id", None) or getattr(agent, "profile_id", None) or "unknown"
    return f"~/.agentira/agents/{agent_id}/home"


def ensure_agent_home_dir(agent) -> str:
    """Return the template path. Filesystem provisioning now happens on
    the daemon side (it owns the host filesystem). Kept for callers
    that still expect a path; semantics: just a resolver, no mkdir."""
    return resolve_agent_home(agent)


def _slugify_project(project) -> str:
    """A filesystem-safe short id for a project's directory name inside
    `<home>/repos/`. Use the id, not the name — names can collide and
    change. Truncated to keep paths tidy."""
    return (getattr(project, "id", None) or "unknown")[:12]


def ensure_worktree_base(project, *, cache_root: str = "~/.agentira/cache/projects") -> str:
    """Return a usable git base for `git worktree add`.

    Same-machine: returns `project.repo_path` if it exists on disk and
    looks like a git repo.

    Cross-machine fallback: if local path missing and `project.repo_url`
    is set, clones into a per-project cache dir and returns that.

    Raises ValueError if neither path is usable.
    """
    import os
    import subprocess
    local = getattr(project, "repo_path", None) or ""
    local = os.path.expanduser(local)
    if local and os.path.isdir(os.path.join(local, ".git")):
        return local
    if local and os.path.isfile(os.path.join(local, "HEAD")):
        # Looks like a bare repo. Worktree add works against bare repos.
        return local
    repo_url = getattr(project, "repo_url", None) or ""
    if not repo_url:
        raise ValueError(
            f"Project {getattr(project, 'id', '?')} has no usable git source "
            f"(repo_path missing, repo_url empty)."
        )
    cache = os.path.join(
        os.path.expanduser(cache_root),
        _slugify_project(project),
        "repo",
    )
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    if not os.path.isdir(os.path.join(cache, ".git")) and not os.path.isfile(
        os.path.join(cache, "HEAD")
    ):
        subprocess.run(
            ["git", "clone", "--quiet", repo_url, cache],
            check=True, timeout=120,
        )
    return cache


def ensure_agent_worktree(agent, project) -> str:
    """Return the TEMPLATE path of the agent's worktree for this project.

    Backend doesn't perform `git worktree add` anymore — that has to
    happen on the daemon side because the user's repo (project.repo_path)
    lives on the daemon's host filesystem, not in the backend container.

    Returns a path template like `~/.agentira/agents/<id>/home/repos/<slug>`.
    The daemon expands `~`, runs `git worktree add` off the user's repo,
    and uses the result as cwd.
    """
    import os
    home_template = resolve_agent_home(agent)
    slug = _slugify_project(project)
    return os.path.join(home_template, "repos", slug)


def conversation_scope_key(*, task_id: str | None = None,
                           project_id: str | None = None,
                           run_id: str | None = None) -> str:
    """Decide which conversation a dispatch belongs to (ADR 008).

    Precedence (first non-empty wins):
      - task_id      → "task:<task_id>"         (all runs of this task share)
      - project_id   → "chat:project:<pid>"     (one chat per project)
      - (default)    → "chat:default"

    `run_id` is accepted for backward-compat but does NOT drive scope
    after AP-93. Old `run:<id>` rows in the DB stay readable but are no
    longer generated for new dispatches.

    Single point of truth — future scopes (threads, comment-threads, etc.)
    extend here without touching call sites.
    """
    if task_id:
        return f"task:{task_id}"
    if project_id:
        return f"chat:project:{project_id}"
    return "chat:default"


# Context assembly lives in its own cohesive module (forge/context.py).
# Re-exported here so existing call sites keep working unchanged.
from backend.forge.context import assemble_context  # noqa: E402


def get_conversation_info(*, agent_id: str, project_id: str | None = None,
                          task_id: str | None = None) -> dict:
    """Returns the conversation state for a given (agent, scope) so the UI
    can show whether this is a fresh chat or a resumed one."""
    scope = conversation_scope_key(task_id=task_id, project_id=project_id)
    with _session() as db:
        conv = (db.query(Conversation)
                  .filter_by(agent_id=agent_id, scope_key=scope)
                  .first())
        msg_count = (db.query(func.count(AgentMessage.id))
                       .filter(AgentMessage.agent_id == agent_id,
                               AgentMessage.scope_key == scope)
                       .scalar() or 0)
    return {
        "scope_key": scope,
        "has_session": bool(conv and conv.runtime_session_id),
        "session_id": (conv.runtime_session_id if conv else "") or "",
        "message_count": int(msg_count),
        "last_used_at": _iso(conv.last_used_at) if conv else None,
    }


def get_runtime_session(*, agent_id: str, scope_key: str) -> str:
    """Return the runtime-native session_id for this conversation (e.g.
    the claude --resume handle), or empty string if no session yet."""
    with _session() as db:
        conv = (db.query(Conversation)
                  .filter_by(agent_id=agent_id, scope_key=scope_key)
                  .first())
        return (conv.runtime_session_id if conv else "") or ""


def upsert_conversation(*, agent_id: str, scope_key: str,
                        runtime_session_id: str = "",
                        rolling_summary: str | None = None,
                        rolling_summary_through_run_id: str | None = None) -> None:
    """Create or update the conversation row. Idempotent — bumps
    last_used_at on every call; stores runtime_session_id if non-empty
    (don't clobber a good handle with an empty one from a failed run).

    `rolling_summary` is the carry-over context for assemble_context's
    compaction — when given (a turn finished with a summary), it refreshes the
    conversation's summary so older turns beyond the token budget stay
    represented instead of silently dropped."""
    if not agent_id or not scope_key:
        return
    with _session() as db:
        conv = (db.query(Conversation)
                  .filter_by(agent_id=agent_id, scope_key=scope_key)
                  .first())
        now = datetime.now(timezone.utc)
        if conv:
            conv.last_used_at = now
            if runtime_session_id:
                conv.runtime_session_id = runtime_session_id
            if rolling_summary:
                conv.rolling_summary = rolling_summary
                conv.rolling_summary_through_run_id = rolling_summary_through_run_id
        else:
            db.add(Conversation(
                agent_id=agent_id,
                scope_key=scope_key,
                runtime_session_id=runtime_session_id or None,
                rolling_summary=rolling_summary or None,
                rolling_summary_through_run_id=rolling_summary_through_run_id,
                last_used_at=now,
            ))
        db.commit()


def clear_conversation(*, agent_id: str, scope_key: str) -> dict:
    """ADR 008: wipe the agent's working memory for one scope.

    Drops the Conversation row (runtime session handle) and all
    AgentMessage rows in that scope. Does NOT touch Run rows, task
    comments, or diffs — those are durable artifacts. Next dispatch
    in this scope starts fresh (no claude --resume).
    """
    if not agent_id or not scope_key:
        return {"error": "agent_id and scope_key required"}
    with _session() as db:
        msg_count = (db.query(AgentMessage)
                       .filter(AgentMessage.agent_id == agent_id,
                               AgentMessage.scope_key == scope_key)
                       .delete(synchronize_session=False))
        conv_count = (db.query(Conversation)
                        .filter_by(agent_id=agent_id, scope_key=scope_key)
                        .delete(synchronize_session=False))
        db.commit()
    return {"ok": True, "messages_deleted": int(msg_count),
            "conversation_deleted": int(conv_count)}


# trace_id → scope_key, populated at dispatch and drained on complete so
# we can persist the runtime session handle to the right conversation.
# In-memory map; if backend restarts mid-dispatch we lose the link and
# silently skip session storage for that one trigger (correctness preserved,
# just no resume for the next message).
_TRACE_SCOPE: dict[str, str] = {}


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
        "runtime_provider": a.runtime.provider if a.runtime else "",
        "runtime_version": a.runtime.version if a.runtime else "",
        # Three-kind identity: derived from role + runtime_id presence.
        # Defensive — list_agents already filters out service_account rows,
        # but a single agent fetched by id might return either kind.
        "kind": "managed_agent" if a.runtime_id else "service_account",
        "default_project_id": a.default_project_id,
        "schedule_cron": a.schedule_cron or "",
        "mcp_servers": json.loads(a.mcp_servers) if a.mcp_servers else [],
        "mcp_disabled": (
            json.loads(a.profile.mcp_disabled) if (a.profile and a.profile.mcp_disabled) else []
        ),
        "mcp_strict": bool(a.profile.mcp_strict) if a.profile else False,
        "mcp_config_override": (a.profile.mcp_config_override if a.profile else "") or "",
        "home_path": (a.profile.home_path if a.profile else None) or resolve_agent_home(a),
        # System agent (Conductor/Concierge) — UI hides delete + offers
        # the special config panel. Conductor cadence config rides along
        # so that panel can read/write it.
        "is_system": bool(a.profile.is_system) if a.profile else False,
        "conductor_enabled": bool(a.profile.conductor_enabled) if a.profile else False,
        "max_concurrent_runs": (a.profile.max_concurrent_runs if a.profile else 1),
        "conductor_tick_seconds": (a.profile.conductor_tick_seconds if a.profile else 60),
        "conductor_report_time": (a.profile.conductor_report_time if a.profile else "09:00"),
        "conductor_report_enabled": bool(a.profile.conductor_report_enabled) if a.profile else True,
        "conductor_plan_interval_minutes": (a.profile.conductor_plan_interval_minutes if a.profile else 10),
        "conductor_active": bool(a.profile.conductor_active) if a.profile else True,
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


def _broadcast_status(run_id: str | None,
                      status: "RunStatus | None",
                      outcome: "RunOutcome | None" = None) -> None:
    """P4: push a run_status frame to every browser subscribed to this
    run via the WS client hub. Best-effort — silent if no event loop
    is available (e.g. some test environments). Schedules the broadcast
    asynchronously; the caller is not blocked on socket writes."""
    if not run_id or status is None:
        return
    try:
        from backend.forge.ws_dispatch import client_hub
        client_hub.broadcast_run_status(
            run_id, status.value,
            outcome.value if outcome is not None else None,
        )
    except Exception:
        pass


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
        # is_work: this run produced durable work, so it surfaces as a "Run"
        # in the UI. False = a pure-chat turn that the UI keeps as chat.
        "is_work": bool(r.is_work),
        # While INTERRUPTING: "pause" (Stop) or "discard" (Discard).
        "interrupt_intent": r.interrupt_intent or None,
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
        # AP-112: editable prompt persisted at prepare time.
        "initial_prompt": r.initial_prompt or "",
        # AP-125: artifacts the agent registered during/after the run.
        "artifacts": _parse_artifacts(r.artifacts_json),
        # AP-123: per-run worktree path + branch — surfaces in the UI so
        # the human can `cd` into the right directory to inspect.
        "worktree_path": r.worktree_path or "",
        "worktree_branch": r.worktree_branch or "",
        # Daemon's materializer outcome — flags the "agent ran in an
        # empty scratch dir because the stamped path didn't exist" case
        # so the user knows what happened without grepping logs.
        "materialize_reason": r.materialize_reason or "",
        # Per-run log directory the daemon tees stdout/stderr into.
        "log_dir": r.log_dir or "",
        # Daemon-reported actual cwd (vs. the backend-stamped
        # worktree_path above) + claude's session id, for the Run page's
        # diagnostic strip. RunDetail.jsx reads these to surface the
        # session.jsonl path and the workdir to `cd` into.
        "workdir": r.workdir or "",
        "session_id": r.session_id or "",
    }


# AP-125: a single artifact is small and structured. Caps keep an agent
# from filling the DB with megabytes of "links."
_ARTIFACT_LABEL_CAP = 200
_ARTIFACT_URL_CAP = 1000
_ARTIFACT_MAX_PER_RUN = 50
_ARTIFACT_KINDS = ("pr", "commit", "file", "url", "log", "report")


def _parse_artifacts(raw: str | None) -> list[dict]:
    """Lenient parse — return [] for unset/malformed blobs so consumers
    don't have to defend."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


def register_run_artifact(*, run_id: str, url: str, label: str = "",
                          kind: str = "url") -> dict:
    """AP-125: append a structured artifact to a Run.

    Called by the agent via the MCP tool of the same name. Idempotent on
    duplicate (url, kind, label); capped at _ARTIFACT_MAX_PER_RUN total
    per run; field widths bounded so a runaway agent can't bloat the row.
    Returns the full artifacts list after the upsert.
    """
    url = (url or "").strip()
    label = (label or "").strip()
    kind = (kind or "url").strip().lower()
    if not url:
        return {"error": "url is required"}
    if kind not in _ARTIFACT_KINDS:
        return {"error": f"kind must be one of: {', '.join(_ARTIFACT_KINDS)}"}
    url = url[:_ARTIFACT_URL_CAP]
    label = label[:_ARTIFACT_LABEL_CAP]

    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return {"error": "run_not_found"}
        existing = _parse_artifacts(r.artifacts_json)
        # Idempotent: if the same (url, kind) is already present, just
        # refresh the label (the agent may have polished it) and return.
        for art in existing:
            if art.get("url") == url and art.get("kind") == kind:
                if label and art.get("label") != label:
                    art["label"] = label
                    r.artifacts_json = json.dumps(existing)
                    db.commit()
                return {"ok": True, "artifacts": existing,
                        "deduplicated": True}
        if len(existing) >= _ARTIFACT_MAX_PER_RUN:
            return {"error": f"artifact cap reached "
                              f"({_ARTIFACT_MAX_PER_RUN}/run)"}
        existing.append({"url": url, "label": label, "kind": kind})
        r.artifacts_json = json.dumps(existing)
        db.commit()
        return {"ok": True, "artifacts": existing}


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
        "host_tools": (json.loads(r.host_tools) if r.host_tools else None),
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
                if entry.get("host_tools") is not None:
                    existing.host_tools = json.dumps(entry["host_tools"])
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
                    host_tools=(json.dumps(entry["host_tools"]) if entry.get("host_tools") is not None else None),
                    status=RuntimeStatus.ONLINE,
                    last_heartbeat=now,
                )
                db.add(rt)
                db.flush()
                results.append(_runtime_to_dict(rt))
        db.commit()
        return {"registered": results}


def heartbeat_runtimes(daemon_id: str, providers: list[str],
                       inflight: list[dict] | None = None) -> dict:
    now = datetime.now(timezone.utc)
    # ADR 009 / B4: refresh the backend's live-turn mirror from the daemon's
    # report. Survives a backend restart (re-populated within one heartbeat)
    # so stop-by-scope and the always-on Stop button don't depend on the
    # in-process _TRACE_SCOPE map.
    try:
        from backend.forge import live_inflight
        live_inflight.set_for_daemon(daemon_id, inflight or [])
    except Exception:  # noqa: BLE001 — never fail a heartbeat on the mirror
        pass
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
        # Stamp the per-run liveness clock for every run the daemon reports
        # as in flight. The reconciler reads this to flip a non-terminal run
        # to FAILED when the daemon stops reporting it — catching a dead
        # dispatch even while the daemon itself is still heartbeating.
        live_run_ids = [e.get("run_id") for e in (inflight or [])
                        if e and e.get("run_id")]
        if live_run_ids:
            (db.query(Run)
               .filter(Run.id.in_(live_run_ids))
               .update({Run.last_heartbeat_at: now},
                       synchronize_session=False))
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
        # Forge surfaces only MANAGED agents — bot profiles bound to a
        # runtime. Service accounts (bot, no runtime) live in Settings
        # → Service Accounts and never appear here.
        agents = (db.query(Agent)
                    .filter(Agent.runtime_id.isnot(None))
                    .order_by(Agent.created_at.desc()).all())
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
    """Create a MANAGED agent. AP-86: every agent has a 1:1 backing Profile
    (bot identity) sharing the same id. Runtime config + identity persist
    together.

    `runtime_id` is REQUIRED — Forge agents are dispatchable by definition.
    To create an API-key-only identity (no runtime), call
    `services.create_service_account()` instead, surfaced via Settings →
    Service Accounts.

    If `profile_id` is given, reuse it (link an existing bot profile to a
    new runtime). Otherwise create both the profile and the agent here.
    """
    if not runtime_id:
        return {"error": "runtime_id is required — managed agents must be bound to a runtime. Use Settings → Service Accounts for an API-key-only identity."}
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
            # Mint an api_key — managed agents call the `agentira` MCP
            # server, which authenticates the agent via this key. Without
            # it the agent gets no agentira tools (can't finish_run,
            # update_task, add_comment).
            import secrets as _secrets
            prof = Profile(
                id=new_id, name=name, display_name=name,
                password_hash="", avatar_url="", webhook_url="",
                role_id=role_row.id,
                model=model,
                runtime_id=runtime_id,
                api_key=_secrets.token_hex(32),
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
    "default_project_id", "mcp_servers", "webhook_url", "mcp_strict",
    "mcp_config_override", "mcp_disabled", "home_path",
    # AP-80 Conductor — these live on Profile (not Agent).
    "conductor_enabled", "max_concurrent_runs",
    # Conductor cadence config (only meaningful on the Conductor profile).
    "conductor_tick_seconds", "conductor_report_time",
    "conductor_report_enabled", "conductor_plan_interval_minutes",
    "conductor_active",
    # AP-155 sandbox config — lives on Profile.
    "sandbox_mode",
}


def update_agent(agent_id: str, **fields) -> dict | None:
    from backend.models import Profile
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return None
        # AP-91: a managed agent can't be downgraded to a service account by
        # clearing its runtime. If you want a service account, create one
        # under Settings → Service Accounts; if you want this agent gone,
        # delete it. Reject empty-string and explicit null.
        if "runtime_id" in fields and a.runtime_id and not fields["runtime_id"]:
            raise ValueError(
                "Cannot clear runtime_id on a managed agent. "
                "Delete the agent or pick a different runtime instead."
            )
        # mcp_servers / mcp_disabled come in as list[str]; persist as JSON.
        if "mcp_servers" in fields and fields["mcp_servers"] is not None:
            fields["mcp_servers"] = json.dumps(list(fields["mcp_servers"]))
        if "mcp_disabled" in fields and fields["mcp_disabled"] is not None:
            fields["mcp_disabled"] = json.dumps(list(fields["mcp_disabled"]))
        # AP-155: empty-string from the UI clears the override (back to
        # workspace default). Validate against the known modes. Applied
        # below the skip-None loop because None IS the legitimate "clear"
        # value here, unlike the other fields.
        sandbox_clear_to_none = False
        if "sandbox_mode" in fields:
            from backend.sandbox import is_valid_mode
            v = (fields["sandbox_mode"] or "").strip() or None
            if not is_valid_mode(v):
                raise ValueError(f"invalid sandbox_mode: {fields['sandbox_mode']!r}")
            fields["sandbox_mode"] = v
            sandbox_clear_to_none = v is None
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
            # AP-155: None is the legitimate clear for sandbox_mode — the
            # generic loop above skips Nones because most fields treat
            # None as "no change requested." Apply the clear here.
            if sandbox_clear_to_none and hasattr(prof, "sandbox_mode"):
                prof.sandbox_mode = None
        db.commit()
        db.refresh(a)
        return _agent_to_dict(a)


def _redact_mcp_config(cfg: dict | None) -> dict:
    """Deep-copy and mask Authorization/secret-bearing fields for display."""
    import copy
    if not cfg:
        return {}
    out = copy.deepcopy(cfg)
    for _name, entry in (out.get("mcpServers") or {}).items():
        if not isinstance(entry, dict):
            continue
        hdrs = entry.get("headers")
        if isinstance(hdrs, dict):
            for hk in list(hdrs.keys()):
                if hk.lower() == "authorization":
                    val = hdrs[hk] or ""
                    # show "Bearer ****abcd" — last 4 chars only
                    tail = val[-4:] if len(val) > 8 else ""
                    hdrs[hk] = f"Bearer ****{tail}"
        env = entry.get("env")
        if isinstance(env, dict):
            for ek in list(env.keys()):
                if any(s in ek.upper() for s in ("TOKEN", "KEY", "SECRET", "PASSWORD")):
                    env[ek] = "****"
    return out


def dispatch_preview(agent_id: str, *, project_id: str | None = None) -> dict:
    """Return what a chat dispatch would send — without dispatching.

    Mirrors `send_runtime_message`'s resolution logic so the UI can show
    the user exactly what's about to ride on the WS frame: repo_path,
    conventions snippet, MCP server list, env vars, system-prompt
    addenda. This is the source of truth for the /context inspector.
    """
    from backend.forge.mcp_registry import build_mcp_config
    from backend.models import Profile, Project
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return {"error": "agent not found"}
        prof = db.get(Profile, a.profile_id) if a.profile_id else None

        # Project resolution — explicit arg wins; else fall back to the
        # agent's default project, else free-form.
        proj_id = project_id or (prof.default_project_id if prof else None)
        proj = db.get(Project, proj_id) if proj_id else None
        repo_path = proj.repo_path if proj else ""
        conventions_md = proj.conventions_md if proj else ""

        # MCP — even free-form chat gets the auto-injected servers
        # (agentira, memory). Project-bound chats also get the per-project
        # memory scoping. Always called now — matches the dispatch path.
        agent_mcp_list = json.loads(a.mcp_servers) if a.mcp_servers else None
        mcp_cfg = build_mcp_config(
            agent_mcp_servers=agent_mcp_list,
            agent_id=a.id,
            project_id=proj_id,
            agent_api_key=(prof.api_key if prof else None),
            mcp_config_override=(prof.mcp_config_override if prof else None),
            disabled_servers=(json.loads(prof.mcp_disabled) if (prof and prof.mcp_disabled) else None),
            agent_home_path=resolve_agent_home(a),
            repo_path=repo_path or None,
        )

        # Env vars the daemon will inject when spawning the runtime. Mirrors
        # what dispatch_trigger packs onto env_extra.
        env_keys = ["AGENTIRA_AGENT_ID", "AGENTIRA_PROJECT_ID"]
        if proj_id:
            env_keys.append("AGENTIRA_REPO_PATH")
        # User-provided agent env_vars (secrets like GH_TOKEN) — names only
        # (don't leak the values to the inspector).
        user_env_names: list[str] = []
        if prof and prof.env_vars:
            try:
                ev = json.loads(prof.env_vars)
                if isinstance(ev, dict):
                    user_env_names = sorted(ev.keys())
            except (ValueError, TypeError):
                pass

        return {
            "agent": {
                "id": a.id,
                "name": a.name,
                "model": (prof.model if prof else a.model) or "",
                "runtime_provider": (a.runtime.provider if a.runtime else "") or "",
            },
            "project": {
                "id": proj_id or "",
                "name": (proj.name if proj else ""),
                "repo_path": repo_path or "",
                "conventions_md_preview": (conventions_md or "")[:300],
                "source": ("explicit" if project_id else
                           ("agent_default" if proj_id else "none")),
            },
            "mcp_servers": (
                sorted((mcp_cfg or {}).get("mcpServers", {}).keys())
                if mcp_cfg else []
            ),
            # Full resolved config — same shape that gets written to the
            # tempfile and passed to claude-code via --mcp-config. Bearer
            # tokens are redacted for display.
            "mcp_config": _redact_mcp_config(mcp_cfg),
            # Layer 1 + Layer 2 view — what the bound runtime brings on its
            # own. Populated at daemon registration; null until the daemon
            # checks in.
            "host_tools": (
                json.loads(a.runtime.host_tools)
                if a.runtime and a.runtime.host_tools
                else None
            ),
            "runtime_provider": a.runtime.provider if a.runtime else "",
            "env_vars": {
                "injected_by_daemon": env_keys,
                "user_provided_names": user_env_names,  # names only, no values
            },
            "system_prompt_addenda": {
                "conventions_pointer_will_be_added": bool(repo_path and conventions_md),
                "memory_addendum_will_be_added": bool(
                    mcp_cfg and "memory" in (mcp_cfg.get("mcpServers") or {})
                ),
                "user_context_preamble": "added per-call from screen route + project",
            },
            "persona_system_prompt": (prof.system_prompt if prof else a.system_prompt) or "",
        }


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
    """Delete an agent. System agents (Conductor, Concierge) are protected
    — they're seeded by Agentira and the workspace depends on them."""
    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return False
        prof = db.get(Profile, a.profile_id) if a.profile_id else None
        if prof and prof.is_system:
            raise ValueError(
                f"{a.name} is a system agent and cannot be deleted."
            )
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
        # Only runs that produced durable work surface in the Runs list. A
        # pure-chat turn is a run row with is_work=False that the UI keeps as
        # chat — that's the "every comment becomes a run" pollution fix. The
        # task-scoped lookup (list_runs_for_task) is unfiltered so the chat
        # Stop button can find an in-flight (is_work=False) run.
        q = q.filter(Run.is_work.is_(True))
        runs = q.order_by(Run.created_at.desc()).offset(offset).limit(limit).all()
        return [_run_to_dict(r) for r in runs]


def get_run(run_id: str) -> dict | None:
    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        return _run_to_dict(r) if r else None


# ── AP-107: Run-investigation MCP service layer ─────────────────────────
#
# These functions back the get_run / get_run_events / get_run_diagnostics
# MCP tools. RBAC: the actor must be a member of the run's project (or
# hold the project.view_all wildcard). System agents already get '*' via
# the auth layer, so they pass.

_DIAGNOSTICS_BYTE_CAP = 50_000   # ~50KB ceiling on the persisted blob
_EVENTS_DEFAULT_LIMIT = 100
_EVENTS_MAX_LIMIT = 500
_EVENT_CONTENT_CAP = 4_000       # per-event content trim to keep payload sane


def _trim_diagnostics_json(diag: dict) -> str:
    """Serialize and cap a diagnostics blob; aggressively trim stderr_tail
    if the JSON is over the cap."""
    blob = dict(diag)
    s = json.dumps(blob, default=str)
    if len(s) <= _DIAGNOSTICS_BYTE_CAP:
        return s
    tail = blob.get("stderr_tail")
    if isinstance(tail, str):
        overflow = len(s) - _DIAGNOSTICS_BYTE_CAP
        blob["stderr_tail"] = tail[-max(0, len(tail) - overflow - 200):]
        s = json.dumps(blob, default=str)
    return s[:_DIAGNOSTICS_BYTE_CAP]


def _assert_run_access(db: Session, run: Run, actor: str) -> None:
    """Raise PermissionError unless `actor` may investigate this run.

    Rule: project.view_all wildcard → always allowed. Otherwise the actor
    must be a member of the run's project. Runs without a project_id are
    only visible to wildcard holders (defensive default)."""
    from backend.auth import has_permission
    from backend.models import ProjectMember
    if has_permission(db, actor, "project.view_all"):
        return
    if not run.project_id:
        raise PermissionError(f"'{actor}' lacks access to run {run.id}")
    profile = db.query(Profile).filter(Profile.name == actor).first()
    if not profile:
        raise PermissionError(f"'{actor}' is not a known profile")
    is_member = (db.query(ProjectMember)
                   .filter_by(project_id=run.project_id, profile_id=profile.id)
                   .first())
    if not is_member:
        raise PermissionError(
            f"'{actor}' is not a member of project {run.project_id}")


def get_run_detail(run_id: str, *, actor: str = "system") -> dict:
    """AP-107: full Run state for an investigator. RBAC-checked."""
    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return {"error": "run_not_found"}
        _assert_run_access(db, r, actor)
        d = _run_to_dict(r)
        d["workdir"] = r.workdir or ""
        d["session_id"] = r.session_id or ""
        return d


def list_run_events(run_id: str, *, actor: str = "system",
                    limit: int = _EVENTS_DEFAULT_LIMIT,
                    offset: int = 0) -> dict:
    """AP-107: paginated event list for a run. Each event is a lean dict;
    `content` is capped to keep payloads small."""
    limit = max(1, min(int(limit or _EVENTS_DEFAULT_LIMIT), _EVENTS_MAX_LIMIT))
    offset = max(0, int(offset or 0))
    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return {"error": "run_not_found"}
        _assert_run_access(db, r, actor)
        q = (db.query(AgentMessage)
               .filter(AgentMessage.run_id == run_id)
               .order_by(AgentMessage.created_at.asc()))
        total = q.count()
        rows = q.offset(offset).limit(limit).all()
        events = []
        for m in rows:
            content = (m.content or "")
            if len(content) > _EVENT_CONTENT_CAP:
                content = content[:_EVENT_CONTENT_CAP] + "…[truncated]"
            events.append({
                "role": m.role.value,
                "tool_name": m.tool_name or "",
                "content": content,
                "created_at": _iso(m.created_at),
            })
        return {"run_id": run_id, "total": total,
                "limit": limit, "offset": offset, "events": events}


def get_run_diagnostics(run_id: str, *, actor: str = "system") -> dict:
    """AP-107: post-mortem bundle for a run — exit code, stderr tail, last
    events, and a status-vs-outcome agreement flag."""
    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return {"error": "run_not_found"}
        _assert_run_access(db, r, actor)
        diag: dict = {}
        if r.diagnostics_json:
            try:
                diag = json.loads(r.diagnostics_json) or {}
            except (TypeError, ValueError):
                diag = {"parse_error": True}
        return {
            "run_id": r.id,
            "status": r.status.value,
            "outcome": r.outcome.value if r.outcome else None,
            "error": r.error,
            "agent_summary": r.summary or "",
            "status_vs_outcome": _status_outcome_agreement(r.status, r.outcome),
            "exit_code": diag.get("exit_code"),
            "stderr_tail": diag.get("stderr_tail", ""),
            "last_events_tail": diag.get("last_events_tail") or [],
            "captured_at": diag.get("captured_at"),
        }


def _status_outcome_agreement(status: "RunStatus",
                              outcome: "RunOutcome | None") -> str:
    """Coarse agreement classifier: did the process result and the agent's
    declared verdict tell the same story?"""
    if outcome is None:
        return "no_verdict"
    s, o = status.value, outcome.value
    failed_status = s in ("failed", "cancelled")
    if failed_status and o == "succeeded":
        return "disagree"
    if s == "completed" and o in ("failed",):
        return "disagree"
    return "agree"


def create_run(*, agent_id: str, task_id: str | None = None,
               project_id: str | None = None, trigger_event: str = "",
               model_used: str = "") -> dict:
    # Delegates to RunManager (backend/forge/runs.py) — single owner of
    # Run lifecycle. Public API kept for back-compat with existing callers.
    from backend.forge import runs as _runs
    return _runs.create(
        agent_id=agent_id, task_id=task_id, project_id=project_id,
        trigger_event=trigger_event, model_used=model_used,
    )


def start_run(run_id: str) -> dict | None:
    from backend.forge import runs as _runs
    return _runs.start(run_id)


def complete_run(run_id: str, *, input_tokens: int = 0, output_tokens: int = 0,
                 cost_usd: float = 0.0, error: str | None = None) -> dict | None:
    from backend.forge import runs as _runs
    return _runs.complete(
        run_id, input_tokens=input_tokens, output_tokens=output_tokens,
        cost_usd=cost_usd, error=error,
    )


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
        # AP-90: Forge counts only runtime-managed agents. Service accounts
        # (role=bot, runtime_id IS NULL) live under Settings → Service Accounts
        # and must not inflate Forge's "total agents" stat.
        managed_filter = Agent.runtime_id.isnot(None)
        total_agents = db.query(func.count(Agent.id)).filter(managed_filter).scalar() or 0
        online_agents = db.query(func.count(Agent.id)).filter(
            managed_filter, Agent.status == AgentStatus.ONLINE
        ).scalar() or 0
        busy_agents = db.query(func.count(Agent.id)).filter(
            managed_filter, Agent.status == AgentStatus.BUSY
        ).scalar() or 0

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
                  scope_key: str | None = None,
                  limit: int = 100, offset: int = 0) -> list[dict]:
    with _session() as db:
        q = db.query(AgentMessage).filter(AgentMessage.agent_id == agent_id)
        if run_id:
            q = q.filter(AgentMessage.run_id == run_id)
        if scope_key:
            q = q.filter(AgentMessage.scope_key == scope_key)
        msgs = q.order_by(AgentMessage.created_at.asc()).offset(offset).limit(limit).all()
        return [_message_to_dict(m) for m in msgs]


def list_conversations(agent_id: str) -> list[dict]:
    """All conversations this agent has, with a friendly label + counts.

    Returns one row per scope_key present in either forge_conversations
    (resume-capable runtimes leave a session row) or forge_messages
    (gateway runtimes only leave messages). Either way the user sees
    a switchable list of past chats."""
    with _session() as db:
        # All scope_keys seen via messages
        msg_rows = (db.query(AgentMessage.scope_key,
                             func.count(AgentMessage.id),
                             func.max(AgentMessage.created_at))
                      .filter(AgentMessage.agent_id == agent_id,
                              AgentMessage.scope_key.isnot(None))
                      .group_by(AgentMessage.scope_key)
                      .all())
        # All scope_keys with a session row
        conv_rows = (db.query(Conversation)
                       .filter(Conversation.agent_id == agent_id)
                       .all())
        # Merge — key by scope_key
        merged: dict[str, dict] = {}
        for sk, cnt, last in msg_rows:
            merged[sk] = {
                "scope_key": sk,
                "message_count": int(cnt or 0),
                "last_used_at": _iso(last),
                "has_session": False,
                "session_id": "",
            }
        for c in conv_rows:
            row = merged.setdefault(c.scope_key, {
                "scope_key": c.scope_key,
                "message_count": 0,
                "last_used_at": _iso(c.last_used_at),
                "has_session": False,
                "session_id": "",
            })
            row["has_session"] = bool(c.runtime_session_id)
            row["session_id"] = c.runtime_session_id or ""
            if c.last_used_at and (not row["last_used_at"] or _iso(c.last_used_at) > row["last_used_at"]):
                row["last_used_at"] = _iso(c.last_used_at)
        # Pretty label per scope
        from backend.models import Project as _Project
        out = []
        for sk, row in merged.items():
            label = _scope_label(db, sk)
            row["label"] = label
            out.append(row)
        out.sort(key=lambda r: r["last_used_at"] or "", reverse=True)
        return out


def _scope_label(db, scope_key: str) -> str:
    """Render a scope key as a human label, e.g.
    chat:project:abc → 'Chat — <project name>'
    chat:default     → 'Chat — no project'
    run:abc          → 'Task run abc'
    """
    if scope_key.startswith("chat:project:"):
        pid = scope_key.split(":", 2)[2]
        from backend.models import Project as _Project
        p = db.get(_Project, pid)
        return f"About {p.name}" if p else f"About project {pid[:8]}"
    if scope_key == "chat:default":
        return "General"
    if scope_key.startswith("chat:user:"):
        return f"General ({scope_key[10:14]})"
    if scope_key.startswith("task:"):
        from backend.models import Task as _Task
        tid = scope_key.split(":", 1)[1]
        t = db.get(_Task, tid)
        return f"Task {t.title}" if (t and t.title) else f"Task {tid[:8]}"
    if scope_key.startswith("run:"):
        return f"Task run {scope_key.split(':',1)[1][:8]}"
    return scope_key


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
                     user_context: dict | None = None,
                     mcp_strict: bool = False,
                     resume_session_id: str = "",
                     scope_key: str = "",
                     # Worktree source info. Daemon uses these to git
                     # worktree the user's repo into the agent's cwd.
                     worktree_source_path: str = "",
                     worktree_source_url: str = "",
                     worktree_branch: str = "",
                     log_dir: str = "") -> dict:
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

    # AP-151 shadow-run trackers — populated inside the with-block only when a
    # shadow Run is created (run-less task chat). Initialized here so the
    # frame-build code below can reference them unconditionally.
    _shadow_task_id = ""
    _shadow_project_id = ""
    _shadow_log_dir = ""

    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a or not a.runtime_id:
            return {"error": "Agent has no bound runtime"}
        runtime = db.get(ForgeRuntime, a.runtime_id)
        if not runtime:
            return {"error": "Runtime not found"}

        # Reserve a Run row for run-less task chat turns. When a chat lands in
        # `task:T` without an explicit run_id (no Run button click, no
        # D-routing resume), reserve a Run row + a log_dir + an AGENTIRA_RUN_ID
        # env var BEFORE dispatch — so the agent can call `register_run_artifact`,
        # the daemon can tee stdout/stderr to a run-keyed dir, and post-mortem
        # diagnostics route correctly. The run starts is_work=False;
        # `complete_trigger` flips it to is_work=True iff the turn produced
        # durable work, which is what surfaces it in the Runs list. A talk-only
        # turn stays is_work=False and the UI keeps it as chat. The row is never
        # deleted — messages keep their run_id and the transcript is intact.
        if (run_id is None and kind == "chat" and scope_key
                and scope_key.startswith("task:")):
            from backend.models import Task as _Task
            from backend.forge import runs as _runs
            _shadow_task_id = scope_key.split(":", 1)[1]
            _shadow_task = db.get(_Task, _shadow_task_id)
            if _shadow_task:
                _shadow_project_id = _shadow_task.project_id or ""
                _wt_path, _wt_branch = _compute_worktree_paths(
                    agent_id=a.id, project_id=_shadow_project_id or None,
                    task_id=_shadow_task_id,
                )
                # Pre-compute log_dir from a provisional id so the row can
                # be inserted with all fields set in one shot. We need the
                # real run_id for the log path though — so insert, flush,
                # then patch log_dir.
                run_id = _runs.create_chat_run_in_session(
                    db,
                    agent_id=a.id,
                    task_id=_shadow_task_id,
                    project_id=_shadow_project_id or None,
                    model_used=a.model or "",
                    initial_prompt=prompt,
                    worktree_path=_wt_path,
                    worktree_branch=_wt_branch,
                    log_dir="",
                )
                _shadow_log_dir = _compute_log_dir(run_id=run_id)
                db.query(Run).filter(Run.id == run_id).update(
                    {"log_dir": _shadow_log_dir}
                )
            else:
                # Task lookup failed — reset trackers; fall through to a
                # normal chat dispatch with no reserved run.
                _shadow_task_id = ""

        # Persist the user message tagged with trace_id (and run_id when present
        # — for shadow runs, this is the freshly-reserved id from above).
        db.add(AgentMessage(
            agent_id=a.id,
            run_id=run_id,
            trace_id=trace_id,
            scope_key=scope_key or None,
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
        persona_prompt = a.system_prompt or ""
        agent_name = a.runtime_agent_name or (a.profile.name if a.profile else a.name)
        # AP-152: agent's api_key — injected into env so the agent can curl
        # `/api/attachments/<id>/download` (binary project attachments) and
        # other authed REST endpoints with $AGENTIRA_API_KEY.
        agent_api_key = (a.profile.api_key if a.profile else "") or ""

        # AP-155: resolve sandbox containment mode for this dispatch.
        # Project override > agent default > workspace default ("off").
        # Phase 1 just logs what would happen; Phase 2 wires per-adapter
        # enforcement (claude --add-dir / bwrap / Docker).
        from backend.sandbox import resolve_mode as _resolve_sandbox
        from backend.models import Project as _Proj
        ctx_for_sandbox = user_context if isinstance(user_context, dict) else {}
        sb_project_id = ctx_for_sandbox.get("project_id")
        sb_project_mode = None
        if sb_project_id:
            sb_proj = db.get(_Proj, sb_project_id)
            sb_project_mode = getattr(sb_proj, "sandbox_mode", None) if sb_proj else None
        sb_agent_mode = a.profile.sandbox_mode if a.profile else None
        sandbox_mode = _resolve_sandbox(
            project_mode=sb_project_mode, agent_mode=sb_agent_mode,
        )
        _dispatch_logger.info(
            "sandbox trace=%s agent=%s project=%s mode=%s "
            "(source: project=%r agent=%r) — Phase 1 log-only",
            trace_id, a.id, sb_project_id or "-",
            sandbox_mode, sb_project_mode, sb_agent_mode,
        )

        # Auto-baked self/project/task awareness preamble.
        # Identity + current screen + project + recent involvement so the
        # agent doesn't open every chat with "this is the start of our
        # conversation." Composed here so it rides on the same
        # --append-system-prompt as the persona. Persona last so it wins
        # on tone/voice conflicts.
        from backend.models import Task as _Task, Project as _Project
        ctx_pre = user_context if isinstance(user_context, dict) else {}
        awareness_lines: list[str] = []
        awareness_lines.append(f"You are {agent_name}, an agent in Agentira (Flowty Forge).")
        if kind == "run_step" and run_id:
            awareness_lines.append(f"This dispatch is part of run {run_id} (a scheduled task run, not free-form chat).")
        else:
            awareness_lines.append("This dispatch is a free-form chat from a human user in the Agentira UI.")
        surface = ctx_pre.get("surface") or ctx_pre.get("route") or ""
        proj_id_ctx = ctx_pre.get("project_id")
        proj_name_ctx = ctx_pre.get("project_name") or ""
        task_id_ctx = ctx_pre.get("task_id")
        if proj_id_ctx:
            if not proj_name_ctx:
                _p = db.get(_Project, proj_id_ctx)
                proj_name_ctx = (_p.name if _p else "") or ""
            awareness_lines.append(f"User is currently viewing project: \"{proj_name_ctx}\" ({proj_id_ctx}).")
        if task_id_ctx:
            _t = db.get(_Task, task_id_ctx)
            if _t:
                awareness_lines.append(f"User has task open: \"{_t.title}\" ({task_id_ctx}).")
        if surface:
            awareness_lines.append(f"UI surface: {surface}.")
        # Recent involvement: top projects by run count (cheap aggregate).
        try:
            inv_rows = (db.query(Run.project_id, func.count(Run.id))
                          .filter(Run.agent_id == a.id, Run.project_id.isnot(None))
                          .group_by(Run.project_id)
                          .order_by(func.count(Run.id).desc())
                          .limit(5).all())
            if inv_rows:
                bits = []
                for pid, cnt in inv_rows:
                    p = db.get(_Project, pid)
                    if p:
                        bits.append(f"{p.name} ({cnt})")
                if bits:
                    awareness_lines.append("Recent projects you've worked on: " + ", ".join(bits) + ".")
            else:
                awareness_lines.append("You have no prior runs on record (this may be your first dispatch).")
        except Exception:
            pass
        awareness_lines.append("Use the agentira MCP tools (get_me, get_my_involvement, list_projects, get_task, list_tasks, add_comment, finish_run, etc.) to look up anything else you need before claiming you don't know.")
        awareness_preamble = "\n".join(awareness_lines)

        if persona_prompt:
            system_prompt = awareness_preamble + "\n\n---\n\n" + persona_prompt
        else:
            system_prompt = awareness_preamble

    # If this trigger belongs to a Run (cron, scheduled task, shadow, …), flip
    # the run state to RUNNING before dispatching. complete_trigger will close
    # it out at the daemon side. Shadow runs were already created with status
    # RUNNING so start_run is a no-op for them.
    if run_id:
        start_run(run_id)

    # Bundle user_context into env_extra so daemon-side code that already
    # consumes env_extra (per AP-51's dispatch shape) picks it up without
    # a new field on the WS frame. The daemon JSON-decodes it.
    env_extra_combined = dict(env_extra or {})
    if user_context:
        env_extra_combined["AGENTIRA_USER_CONTEXT_JSON"] = json.dumps(user_context)

    # AP-151: for shadow runs (created above when no explicit run_id was
    # passed), inject AGENTIRA_RUN_ID / TASK_ID / PROJECT_ID so the agent's
    # MCP tools (`register_run_artifact` etc.) can target the right run, and
    # use the shadow's log_dir for the dispatch frame. dispatch_pending_run
    # sets these for run-button dispatches; setdefault keeps that intact.
    if run_id:
        env_extra_combined.setdefault("AGENTIRA_RUN_ID", run_id)
        if _shadow_task_id:
            env_extra_combined.setdefault("AGENTIRA_TASK_ID", _shadow_task_id)
        if _shadow_project_id:
            env_extra_combined.setdefault("AGENTIRA_PROJECT_ID", _shadow_project_id)
    # AP-155: tell the daemon what containment mode the backend resolved
    # for this dispatch. Phase 1: daemon logs and proceeds as-is. Phase 2:
    # adapter honors per its declared capabilities.
    env_extra_combined.setdefault("AGENTIRA_SANDBOX_MODE", sandbox_mode)
    # AP-152: agent's own API key so it can authenticate REST calls
    # (e.g. download binary attachments). setdefault so explicit callers win.
    if agent_api_key:
        env_extra_combined.setdefault("AGENTIRA_API_KEY", agent_api_key)
    effective_log_dir = log_dir or _shadow_log_dir

    if scope_key:
        _TRACE_SCOPE[trace_id] = scope_key

    _dispatch_coro(hub.dispatch_trigger(
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
        worktree_source_path=worktree_source_path,
        worktree_source_url=worktree_source_url,
        worktree_branch=worktree_branch,
        conventions_md=conventions_md,
        mcp_config_json=mcp_config_json,
        mcp_strict=mcp_strict,
        resume_session_id=resume_session_id,
        env_extra=env_extra_combined,
        run_token=run_token,
        log_dir=effective_log_dir,
        # ADR 009 / B1: the scope rides the frame so the daemon can key its
        # durable on-disk inflight registry by scope (one live turn per
        # scope), derive task_id for a chat dispatch, and let stop-by-scope
        # find the right process even across a backend restart.
        scope_key=scope_key or "",
    ))
    return {"ok": True, "trace_id": trace_id, "run_id": run_id}


def _build_task_prompt(task, extra_context: str = "") -> str:
    """Compose the agent prompt from a task's title + description + DoD.

    Pure function — takes a Task ORM object (loaded in an active session)
    and returns the prompt with a `{run_id}` placeholder. The caller
    substitutes the real run_id once the Run row exists.
    """
    task_title = task.title or ""
    task_description = task.description or ""
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

    parts = [f"# Task: {task_title}"]
    if task_description:
        parts.append("\n## Description\n" + task_description)
    if dod_text:
        parts.append("\n## Definition of Done\n" + dod_text)
    parts.append("\nWork on this task.")
    if extra_context:
        parts.append("\n## Follow-up from the user\n" + extra_context)
    parts.append(
        "\n## Output contract — do NOT skip this\n"
        "A task is only \"succeeded\" if there is something the human can\n"
        "look at when they open the Run page. Before calling finish_run\n"
        "with outcome=\"succeeded\":\n"
        "\n"
        "1. **Commit your changes** in the worktree you're in. The Run page's\n"
        "   Changes tab reads from `git diff` — if you didn't commit, the\n"
        "   page shows nothing and the work looks lost.\n"
        "2. **Register at least one artifact** via\n"
        "   mcp__agentira__register_run_artifact for the deliverable —\n"
        "   the PR URL (kind=\"pr\"), a generated report (kind=\"report\"),\n"
        "   a deployed preview (kind=\"url\"), or a key file (kind=\"file\").\n"
        "   This is what shows up in the \"Here's what got built\" panel\n"
        "   on the Run page. No artifact = the human can't tell what you did.\n"
        "\n"
        "If you didn't actually produce a deliverable, **do NOT pretend you\n"
        "did**. Call finish_run with outcome=\"blocked\" (and a real\n"
        "explanation in summary) or outcome=\"failed\" instead.\n"
        "\nWhen you finish, call mcp__agentira__finish_run with:\n"
        "  - run_id: \"{run_id}\"\n"
        "  - outcome: one of \"succeeded\" | \"blocked\" | \"needs_input\" | \"failed\"\n"
        "  - summary: one paragraph describing what changed (or what's blocking).\n"
        "Use \"blocked\" when you can't proceed without external input "
        "(missing credentials, ambiguous spec, broken dependency)."
    )
    return "\n".join(parts)


def prepare_task_run(*, task_id: str, agent_id: str,
                     extra_context: str = "") -> dict:
    """AP-112: build the prompt and create a READY Run — do NOT dispatch.

    The run state machine: prepare → READY (prompt persisted, agent
    assigned, waiting on the user) → dispatch → RUNNING. The user lands
    on the run page, edits the prompt if they want, and clicks Start.

    `extra_context` — optional free text folded into the prompt (AP-120
    uses it to carry a user's follow-up message into a retry run).
    """
    from backend.models import Task
    with _session() as db:
        task = db.get(Task, task_id)
        if not task:
            return {"error": "Task not found"}
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            return {"error": "Agent not found"}
        if not agent.runtime_id:
            return {"error": "Agent has no bound runtime"}
        prompt_template = _build_task_prompt(task, extra_context)
        project_id = task.project_id
        model = agent.model or ""

    run = create_run(
        agent_id=agent_id,
        task_id=task_id,
        project_id=project_id,
        trigger_event="task.scheduled",
        model_used=model,
    )
    run_id = run["id"]
    # Substitute the real run_id, persist the prompt for editing, and flip
    # PENDING (the create_run default) → READY so the UI knows this run is
    # waiting on the user, not on the system.
    prompt = prompt_template.replace("{run_id}", run_id)
    # Stamp the task-scoped worktree path + branch on the row. Shared
    # across all runs and chats for this (agent, task) so claude's
    # `--resume` (cwd-keyed) works.
    worktree_path, worktree_branch = _compute_worktree_paths(
        agent_id=agent_id, project_id=project_id, task_id=task_id,
    )
    log_dir = _compute_log_dir(run_id=run_id)
    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if r:
            r.initial_prompt = prompt
            r.status = RunStatus.READY
            r.worktree_path = worktree_path
            r.worktree_branch = worktree_branch
            r.log_dir = log_dir
            db.commit()
            db.refresh(r)
            return _run_to_dict(r)
    return run


def _compute_log_dir(*, run_id: str) -> str:
    """Per-run log directory. Tilde-prefixed; daemon expanduser's at use
    time. Daemon writes stdout.log / stderr.log / meta.json here."""
    return f"~/.agentira/runs/{run_id}/"


# Worktree path + branch are stamped on the Run row at prepare time and
# passed to the daemon at dispatch. Pinned BY TASK SCOPE — every run and
# chat dispatch for the same (agent, task) shares one worktree so
# claude's `--resume <session_id>` (which is keyed by cwd at session
# creation) keeps working across runs and chats.
#
#   path:   ~/.agentira/agents/<agent_id>/home/repos/<project_id>/task-<task_id[:8]>/
#   branch: agent/<agent_id[:8]>/task/<task_id[:8]>
#
# Tradeoff vs the earlier per-run scheme (AP-123): two concurrent runs
# on the same (agent, task) would collide in the shared working tree,
# so runs serialize per (agent, task). Concurrent runs across DIFFERENT
# tasks for the same agent still work (capped by max_concurrent_runs).

def _compute_worktree_paths(*, agent_id: str, project_id: str | None,
                            task_id: str | None) -> tuple[str, str]:
    """Return (worktree_path, worktree_branch) pinned to (agent, task).

    Returns ("", "") when there's no task scope or project — the daemon
    falls back to the agent's home dir as today.

    Path is tilde-prefixed and NOT expanded here: backend may run in a
    container where `~` = `/root`, but the daemon runs on the host.
    Expansion happens daemon-side at use time.
    """
    if not project_id or not task_id:
        return "", ""
    path = (f"~/.agentira/agents/{agent_id}/home/repos/"
            f"{project_id}/task-{task_id[:8]}/")
    branch = f"agent/{agent_id[:8]}/task/{task_id[:8]}"
    return path, branch


# Sent as the prompt when a PAUSED run is resumed. claude --resume reloads
# the full conversation, so this is just a nudge to continue — NOT the task
# prompt (re-sending that would make the agent restart from scratch).
_RESUME_CONTINUATION_PROMPT = (
    "Continue this task from where you paused. Your prior progress is in "
    "the conversation above — pick up where you left off and finish, then "
    "call mcp__agentira__finish_run as instructed earlier."
)


def dispatch_pending_run(*, run_id: str,
                         prompt_override: str | None = None,
                         resume: bool = False) -> dict:
    """AP-112: dispatch a READY/PENDING run, optionally with an edited prompt.

    Loads the Run, resolves the run-context bundle (repo, MCP, env, scope)
    and dispatches a trigger of kind=run_step. The dispatched prompt is the
    override if given, else the prompt stored on the Run at prepare time.
    `dispatch_trigger` flips the run READY → RUNNING via `start_run`.

    `resume=True` relaunches a PAUSED run: the run must be PAUSED, a short
    continuation nudge is sent instead of the task prompt (claude --resume
    reloads the conversation), and `initial_prompt` is left untouched.
    """
    import json as _json
    import uuid
    from backend.models import Task, Project, Profile as _Profile
    from backend.forge.mcp_registry import build_mcp_config

    with _session() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            return {"error": "Run not found"}
        if resume:
            # resume_run flips PAUSED → PENDING before calling us (re-dispatch);
            # accept both. The daemon's first event / start_run flips → RUNNING.
            if run.status not in (RunStatus.PAUSED, RunStatus.PENDING):
                return {"error": f"Run is {run.status.value}; "
                                  "only PAUSED runs can be resumed"}
        elif run.status not in (RunStatus.READY, RunStatus.PENDING):
            return {"error": f"Run is {run.status.value}; "
                              "only READY/PENDING runs can be dispatched"}
        agent = db.query(Agent).filter(Agent.id == run.agent_id).first()
        if not agent:
            return {"error": "Agent not found"}
        if not agent.runtime_id:
            return {"error": "Agent has no bound runtime"}

        # Capture FKs as plain values — the ORM `run`/`agent` objects become
        # detached after the session closes; later attribute access would
        # raise DetachedInstanceError and surface as a 500.
        task_id = run.task_id
        project_id = run.project_id
        agent_id = agent.id
        task = db.get(Task, task_id) if task_id else None

        # Concurrency model: cwd is pinned per (agent, task), so two
        # runs on the SAME task would clobber each other's working tree.
        # Serialize per (agent, task), then cap total runs across tasks
        # by the agent's max_concurrent_runs.
        if task_id:
            same_task_in_flight = (db.query(Run)
                                     .filter(Run.agent_id == agent_id,
                                             Run.task_id == task_id,
                                             Run.status == RunStatus.RUNNING,
                                             Run.id != run_id)
                                     .count())
            if same_task_in_flight:
                return {"error": (
                    "Agent already running this task. Wait for it to "
                    "finish or stop it first.")}
            from backend.models import Profile as _Profile
            prof = db.get(_Profile, agent.profile_id) if agent.profile_id else None
            cap = max(1, int(prof.max_concurrent_runs or 1)) if prof else 1
            in_flight = (db.query(Run)
                           .filter(Run.agent_id == agent_id,
                                   Run.status == RunStatus.RUNNING,
                                   Run.task_id.isnot(None),
                                   Run.id != run_id)
                           .count())
            if in_flight >= cap:
                return {"error": (
                    f"Agent at concurrency cap ({in_flight}/{cap} task "
                    f"runs in flight). Wait for one to finish, raise "
                    f"max_concurrent_runs, or stop a run first.")}

        if resume:
            # Resume: by default a continuation nudge; but if a steer message
            # was provided (chat-during-run, or resuming a parked run with the
            # user's new instruction), dispatch THAT as the next turn instead.
            # initial_prompt (the original task prompt) is left untouched; the
            # session is reloaded via --resume.
            prompt = prompt_override or _RESUME_CONTINUATION_PROMPT
        else:
            # Persist the (possibly edited) prompt and pick what we dispatch.
            if prompt_override is not None:
                run.initial_prompt = prompt_override
                db.commit()
            prompt = run.initial_prompt
            if not prompt:
                # Defensive: prepare always sets it, but a run created by a
                # legacy path may not have one.
                if task:
                    prompt = _build_task_prompt(task).replace("{run_id}", run_id)
                    run.initial_prompt = prompt
                    db.commit()
                else:
                    return {"error": "Run has no prompt and no task to derive one"}

        # cwd is a path TEMPLATE (with `~` unexpanded) — backend can't
        # expand it because backend lives in docker (`~` = `/root`) but
        # the daemon runs on the host.
        project = db.get(Project, project_id) if project_id else None
        conventions_md = (project.conventions_md or "") if project else ""
        if project:
            # AP-123: use the per-run worktree the Run row carries. Falls
            # back to the legacy shared-per-agent worktree for legacy rows
            # without the new fields set (e.g. runs created before this
            # migration), so old data keeps working.
            run_log_dir = run.log_dir or ""
            if run.worktree_path and run.worktree_branch:
                repo_path = run.worktree_path
                worktree_branch = run.worktree_branch
            else:
                repo_path = ensure_agent_worktree(agent, project)   # template
                worktree_branch = f"agent/{agent.id}/work"
            # AP-121: pick the right repo for THIS task. Single-repo
            # projects (legacy) → resolve_project_repo synthesizes a row
            # from Project.repo_path so this code path is unchanged.
            # Multi-repo projects → uses the task's repo_name, defaults
            # to the primary repo when NULL.
            from backend.models import Task as _Task
            task_row = db.get(_Task, task_id) if task_id else None
            task_repo_name = task_row.repo_name if task_row else None
            from backend import services as _core_services
            chosen = _core_services.resolve_project_repo(
                project.id, task_repo_name,
            )
            if chosen:
                worktree_source_path = chosen["repo_path"] or ""
                worktree_source_url = chosen["repo_url"] or ""
            else:
                worktree_source_path = project.repo_path or ""
                worktree_source_url = (getattr(project, "repo_url", None) or "")
        else:
            repo_path = ensure_agent_home_dir(agent)            # template
            worktree_source_path = ""
            worktree_source_url = ""
            worktree_branch = ""

        # Agent toolkit — list of opt-in MCP server names.
        agent_mcp_servers: list[str] = []
        if agent.mcp_servers:
            try:
                parsed = _json.loads(agent.mcp_servers)
                if isinstance(parsed, list):
                    agent_mcp_servers = [str(s) for s in parsed]
            except Exception:
                pass

        prof = db.get(_Profile, agent.profile_id) if agent.profile_id else None
        agent_api_key = prof.api_key if prof else None
        agent_mcp_strict = bool(prof.mcp_strict) if prof else False
        agent_mcp_override = prof.mcp_config_override if prof else None
        agent_mcp_disabled = (
            _json.loads(prof.mcp_disabled) if (prof and prof.mcp_disabled) else None
        )
        rt_for_caps = (
            db.get(ForgeRuntime, agent.runtime_id) if agent.runtime_id else None
        )
        rt_caps_json = rt_for_caps.capabilities if rt_for_caps else None
        agent_home = resolve_agent_home(agent)

    mcp_config = build_mcp_config(
        agent_mcp_servers=agent_mcp_servers,
        agent_id=agent_id,
        project_id=project_id,
        agent_api_key=agent_api_key,
        mcp_config_override=agent_mcp_override,
        disabled_servers=agent_mcp_disabled,
        agent_home_path=agent_home,
        repo_path=repo_path or None,
    )
    mcp_config_json = _json.dumps(mcp_config)

    # Per-run token — used by finish_run to scope the agent's outcome to
    # this specific run. Rides on the frame as AGENTIRA_RUN_TOKEN.
    run_token = uuid.uuid4().hex
    env_extra = {
        "AGENTIRA_RUN_ID": run_id,
        "AGENTIRA_TASK_ID": task_id or "",
        "AGENTIRA_PROJECT_ID": project_id or "",
        "AGENTIRA_AGENT_ID": agent_id,
        "AGENTIRA_RUN_TOKEN": run_token,
    }

    # ADR 008: task-scope (not run-scope) so multiple runs of the same task
    # share one conversation. Agent picks up where it left off across re-runs.
    scope = conversation_scope_key(task_id=task_id, project_id=project_id)
    caps = (_json.loads(rt_caps_json) if rt_caps_json else [])
    resume_id = ""
    if "resume" in caps:
        resume_id = get_runtime_session(agent_id=agent_id, scope_key=scope)

    result = dispatch_trigger(
        agent_id, prompt,
        run_id=run_id, kind="run_step",
        repo_path=repo_path,
        worktree_source_path=worktree_source_path,
        worktree_source_url=worktree_source_url,
        worktree_branch=worktree_branch,
        conventions_md=conventions_md,
        mcp_config_json=mcp_config_json,
        mcp_strict=agent_mcp_strict,
        env_extra=env_extra,
        run_token=run_token,
        resume_session_id=resume_id,
        scope_key=scope,
        log_dir=run_log_dir,
    )
    return {**result, "run_id": run_id, "task_id": task_id}


def discard_pending_run(*, run_id: str) -> dict:
    """AP-112: delete a never-dispatched READY run.

    User clicked Run → landed on the prompt-edit screen → decided not to
    start. Only READY/PENDING runs are discardable — RUNNING+ needs cancel.
    """
    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return {"error": "Run not found"}
        if r.status not in (RunStatus.READY, RunStatus.PENDING):
            return {"error": f"Run is {r.status.value}; cannot discard"}
        db.delete(r)
        db.commit()
    return {"ok": True}


def ready_checks(run_id: str) -> dict:
    """AP-113: pre-run validation for a READY run.

    Returns a checklist the UI shows before the user clicks Start —
    runtime, API key, MCP, environment/keys, repo, task context. Checks
    are advisory: only a missing runtime is fatal (and dispatch enforces
    that anyway). `ready` is False when any check is a hard fail.
    """
    import json as _json
    from backend.models import Task, Project, Profile as _Profile

    checks: list[dict] = []

    def add(key: str, label: str, status: str, detail: str) -> None:
        checks.append({"key": key, "label": label,
                       "status": status, "detail": detail})

    with _session() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            return {"error": "Run not found"}
        agent = db.query(Agent).filter(Agent.id == run.agent_id).first()
        if not agent:
            return {"error": "Agent not found"}
        prof = db.get(_Profile, agent.profile_id) if agent.profile_id else None
        task = db.get(Task, run.task_id) if run.task_id else None
        project = db.get(Project, run.project_id) if run.project_id else None
        runtime = (db.get(ForgeRuntime, agent.runtime_id)
                   if agent.runtime_id else None)

        # Runtime bound — the only fatal check.
        if runtime:
            add("runtime", "Runtime bound", "ok",
                f"{runtime.provider} ({runtime.binary_path})")
        else:
            add("runtime", "Runtime bound", "fail",
                "Agent has no runtime — it cannot run. Bind one in Config.")

        # Runtime online.
        if runtime:
            if _is_runtime_online(runtime):
                add("runtime_online", "Runtime online", "ok",
                    "Daemon is connected.")
            else:
                add("runtime_online", "Runtime online", "warn",
                    "Daemon offline — the run queues until it reconnects.")

        # API key — needed for the agentira MCP (finish_run et al).
        if prof and prof.api_key:
            add("api_key", "Agent API key", "ok",
                "Agentira MCP tools are authenticated.")
        else:
            add("api_key", "Agent API key", "warn",
                "No API key — the agent can't call finish_run or other "
                "agentira MCP tools.")

        # MCP toolkit — built-ins are always injected; opt-ins are listed.
        opt_ins: list[str] = []
        if agent.mcp_servers:
            try:
                parsed = _json.loads(agent.mcp_servers)
                if isinstance(parsed, list):
                    opt_ins = [str(s) for s in parsed]
            except Exception:
                pass
        add("mcp", "MCP toolkit", "ok",
            "Built-ins (agentira, memory) auto-included"
            + (f"; opt-ins: {', '.join(opt_ins)}" if opt_ins else "."))

        # Environment keys.
        env: dict = {}
        if prof and prof.env_vars:
            try:
                env = _json.loads(prof.env_vars) or {}
            except Exception:
                env = {}
        env_names = sorted(env.keys())
        add("env", "Environment keys", "ok",
            ("Configured: " + ", ".join(env_names)) if env_names
            else "No custom environment keys configured.")

        # Repo / workdir.
        if project:
            if project.repo_path:
                add("repo", "Project repository", "ok", project.repo_path)
            else:
                add("repo", "Project repository", "warn",
                    "Project has no repo_path — the agent runs in a bare "
                    "home dir, not your code.")
        else:
            add("repo", "Project repository", "ok",
                "No project bound — generic run.")

        # Git credentials — only relevant when there's a repo to push to.
        if project and project.repo_path:
            has_gh = any(k.upper() in ("GH_TOKEN", "GITHUB_TOKEN")
                         for k in env_names)
            if has_gh:
                add("git_token", "Git credentials", "ok",
                    "A GitHub token is configured.")
            else:
                add("git_token", "Git credentials", "warn",
                    "No GH_TOKEN/GITHUB_TOKEN env var — pushing branches or "
                    "opening PRs may fail.")

        # Task context — a thin task makes a thin prompt.
        if task:
            has_desc = bool((task.description or "").strip())
            has_dod = False
            if task.dod_items:
                try:
                    has_dod = bool(_json.loads(task.dod_items))
                except Exception:
                    pass
            if has_desc or has_dod:
                bits = []
                if has_desc:
                    bits.append("a description")
                if has_dod:
                    bits.append("a definition of done")
                add("context", "Task context", "ok",
                    "Task has " + " and ".join(bits) + ".")
            else:
                add("context", "Task context", "warn",
                    "Task has no description or definition of done — the "
                    "agent gets a thin prompt.")
        else:
            add("context", "Task context", "ok",
                "No task — the run carries its own prompt.")

    fatal = any(c["status"] == "fail" for c in checks)
    return {
        "run_id": run_id,
        "ready": not fatal,
        "checks": checks,
        "summary": {
            "ok": sum(1 for c in checks if c["status"] == "ok"),
            "warn": sum(1 for c in checks if c["status"] == "warn"),
            "fail": sum(1 for c in checks if c["status"] == "fail"),
        },
    }


def schedule_task_run(*, task_id: str, agent_id: str,
                      extra_context: str = "") -> dict:
    """Prepare + immediately dispatch a Run — the auto-start path.

    AP-112 split run start into prepare (build prompt, READY) + dispatch
    (start) so the user can review the prompt first. This wrapper keeps
    the no-edit auto-start behaviour for non-interactive callers: the
    Conductor, webhooks, and the AP-120 failed-run retry.
    """
    prepared = prepare_task_run(task_id=task_id, agent_id=agent_id,
                                extra_context=extra_context)
    if prepared.get("error"):
        return prepared
    result = dispatch_pending_run(run_id=prepared["id"])
    # If dispatch was refused (e.g. the agent is already running a task),
    # don't leave the prepared READY run orphaned — discard it so the
    # caller (Conductor / webhook) can cleanly retry on the next tick.
    if result.get("error"):
        discard_pending_run(run_id=prepared["id"])
    return result


def retry_run(run_id: str, *, actor: str = "system") -> dict:
    """Explicit user-driven restart of a failed/cancelled run.

    AP-120 already retries implicitly when the user chats into a task
    whose latest run failed. This is the explicit Restart-button path:
    same task + same agent, scheduled fresh, with a one-line context
    hint so the agent knows it's a retry. The chat thread gets a SYSTEM
    breadcrumb pointing back at the prior run.

    Refuses to restart in-flight runs (PENDING/RUNNING/PAUSED) and
    free-floating chat runs (no task_id). SUCCEEDED runs are
    deliberately allowed too — sometimes the user wants to re-do work
    even after a clean completion (e.g. plan got obsolete).
    """
    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if not r:
            return {"error": "run_not_found"}
        try:
            _assert_run_access(db, r, actor)
        except PermissionError as exc:
            return {"error": str(exc)}
        if not r.task_id:
            return {"error": "cannot restart a free-floating chat run"}
        if r.status in (RunStatus.PENDING, RunStatus.RUNNING,
                        RunStatus.PAUSED, RunStatus.INTERRUPTING):
            return {"error":
                    f"Run is {r.status.value}; stop or wait for it before restarting"}
        prior_outcome = (r.outcome.value if r.outcome else r.status.value)
        task_id = r.task_id
        agent_id = r.agent_id

    new = schedule_task_run(
        task_id=task_id, agent_id=agent_id,
        extra_context=(
            f"Restart of run {run_id} (previous outcome: {prior_outcome}). "
            "Read the prior run's chat history if you need context for "
            "what to do differently."
        ),
    )
    if new.get("error"):
        return new

    new_run_id = new.get("run_id") or new.get("id") or ""
    if new_run_id:
        with _session() as db:
            db.add(AgentMessage(
                agent_id=agent_id, run_id=new_run_id,
                scope_key=f"task:{task_id}",
                role=MessageRole.SYSTEM,
                content=f"Restarted from run {run_id} (previous outcome: {prior_outcome}).",
            ))
            db.commit()
    return new


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
        # ADR 009 / B6: scope so the daemon can resolve the live turn by
        # scope when the trace mapping was lost (backend restart).
        signal_scope_key = f"task:{run.task_id}" if run.task_id else ""
        last_msg = (db.query(AgentMessage)
                    .filter(AgentMessage.run_id == run_id)
                    .order_by(AgentMessage.created_at.desc())
                    .first())
        trace_id = last_msg.trace_id if last_msg else ""
        if target_status is not None:
            run.status = target_status
            db.commit()
            db.refresh(run)
            _broadcast_status(run_id, target_status)
        run_dict = _run_to_dict(run)

    if runtime_id:
        try:
            _dispatch_coro(hub.dispatch_signal(
                runtime_id=runtime_id,
                signal=frame_type,
                trace_id=trace_id,
                run_id=run_id,
                scope_key=signal_scope_key,
            ))
        except Exception:
            pass
    return {"ok": True, "run": run_dict}


def pause_run(run_id: str) -> dict:
    """Pause a run. The daemon terminates the CLI subprocess (SIGTERM) —
    a live claude process can't be safely frozen, SIGSTOP corrupts its
    streaming sockets. The run is parked at status=INTERRUPTING
    (interrupt_intent="pause") with `stop_requested_at` stamped; the daemon's
    trigger-complete(paused=True) is what flips it to terminal PAUSED with the
    session_id persisted. `resume_run` relaunches it via `claude --resume`.
    Best-effort: openclaw HTTP runs aren't pausable (the request completes)."""
    res = _signal_run(run_id, "pause", RunStatus.INTERRUPTING)
    if res.get("ok"):
        with _session() as db:
            r = db.query(Run).filter(Run.id == run_id).first()
            if r:
                r.stop_requested_at = datetime.now(timezone.utc)
                r.interrupt_intent = "pause"
                db.commit()
    return res


def resume_run(run_id: str) -> dict:
    """Resume a PAUSED run by relaunching it.

    Pausing terminated the subprocess, so there is nothing to un-freeze.
    Resume re-dispatches a fresh process that reloads the conversation
    from the captured session via `claude --resume` and continues. The
    run_id is reused — the run is one continuous record across the pause.

    The row flips PAUSED→PENDING here (re-dispatch); the daemon's first event
    post (via start_run) flips it to RUNNING.
    """
    with _session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        if r and r.status == RunStatus.PAUSED:
            r.status = RunStatus.PENDING
            r.interrupt_intent = None
            db.commit()
            _broadcast_status(run_id, RunStatus.PENDING)
    return dispatch_pending_run(run_id=run_id, resume=True)


def scope_live(scope_key: str) -> dict:
    """ADR 009 / E2: whether a turn is live for this scope, from the
    daemon-reported live-inflight mirror (survives a backend restart).
    Lets the chat UI keep Stop available while anything is running."""
    from backend.forge import live_inflight
    trace = live_inflight.lookup_trace(scope_key)
    return {"live": bool(trace), "trace_id": trace or ""}


def record_task_comment(*, agent_id: str, task_id: str, actor: str,
                        content: str) -> None:
    """Persist a human comment into the agent's task chat WITHOUT dispatching.

    A plain comment should be visible to the agent as context on its next turn,
    but it must NOT auto-start a run (AP-184). Stored as a USER message in the
    task scope so assemble_context picks it up when the agent next runs."""
    with _session() as db:
        db.add(AgentMessage(
            agent_id=agent_id,
            scope_key=f"task:{task_id}",
            role=MessageRole.USER,
            content=f"[Comment from {actor}] {content}",
        ))
        db.commit()


def list_queued_messages(*, agent_id: str, scope_key: str) -> list[dict]:
    """Messages queued behind the active turn in this conversation (AP-179),
    oldest first — the chat UI renders them as "queued" pills under the live
    turn so the user sees exactly what runs next."""
    from backend.forge import msg_queue
    return msg_queue.list_for_scope(agent_id=agent_id, scope_key=scope_key)


def stop_chat(*, agent_id: str, scope_key: str) -> dict:
    """ADR 008: Stop button in chat.

    Cancels the in-flight dispatch for this (agent, scope). If the scope
    is a task scope AND there's an active Run for that task, also pauses
    the run (so the agent's working memory is preserved and a follow-up
    message resumes it via claude --resume).
    """
    import asyncio
    from backend.forge.ws_dispatch import hub
    if not agent_id or not scope_key:
        return {"error": "agent_id and scope_key required"}

    # Find the latest active trace_id for THIS scope (this chat thread).
    # First the in-memory map; if it was lost (backend restart) recover
    # the trace from persisted messages tagged with this scope_key. This
    # keeps the cancel targeted at the specific chat the user is in —
    # not everything the agent is doing.
    trace_id = ""
    for tid, sc in list(_TRACE_SCOPE.items()):
        if sc == scope_key:
            trace_id = tid  # last one wins (insertion order)
    # ADR 009 / B4: if the in-process map missed (e.g. backend restarted),
    # use the daemon-reported live-turn mirror — authoritative and fresher
    # than the persisted-message fallback below (which can point at a
    # finished trace). The daemon also resolves by scope_key on its side,
    # so this is mainly for an accurate response/log.
    if not trace_id:
        from backend.forge import live_inflight
        trace_id = live_inflight.lookup_trace(scope_key)
    if not trace_id:
        with _session() as db:
            m = (db.query(AgentMessage)
                   .filter(AgentMessage.scope_key == scope_key,
                           AgentMessage.agent_id == agent_id,
                           AgentMessage.trace_id.isnot(None),
                           AgentMessage.trace_id != "")
                   .order_by(AgentMessage.created_at.desc())
                   .first())
            if m:
                trace_id = m.trace_id

    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        runtime_id = a.runtime_id if a else None

    paused_run_id = None
    if scope_key.startswith("task:"):
        task_id = scope_key.split(":", 1)[1]
        with _session() as db:
            active = (db.query(Run)
                        .filter(Run.task_id == task_id,
                                Run.agent_id == agent_id,
                                Run.status.in_([RunStatus.RUNNING, RunStatus.PENDING]))
                        .order_by(Run.created_at.desc())
                        .first())
            if active:
                paused_run_id = active.id

    if paused_run_id:
        # pause_run also fires the WS pause frame and flips status.
        pause_run(paused_run_id)
        return {"ok": True, "paused_run_id": paused_run_id,
                "cancelled_trace_id": trace_id or None}

    # No active Run row — fire a bare cancel to the daemon. Guard with a
    # daemon-online check so the UI gets a clear error instead of a
    # silent ok=True when the WS link is half-open (the failure mode
    # that hid every "zombie chat I can't stop" bug).
    if runtime_id:
        from backend.forge.ws_dispatch import hub as _hub
        online = any(runtime_id in c.runtime_ids for c in _hub._conns.values())
        if not online:
            return {"ok": False, "error": (
                "Daemon offline — cancel could not be delivered. The "
                "chat process may still be running on the host. Restart "
                "the daemon or kill the subprocess manually.")}
        try:
            _dispatch_coro(hub.dispatch_cancel(
                runtime_id=runtime_id, trace_id=trace_id,
                scope_key=scope_key,
            ))
        except Exception:
            pass

    return {"ok": True, "paused_run_id": paused_run_id,
            "cancelled_trace_id": trace_id or None}


def cancel_run(run_id: str) -> dict:
    """Cancel a pending or running Run. Delegates to RunManager."""
    from backend.forge import runs as _runs
    return _runs.cancel(run_id)


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
        # Empty-success guard: an agent can't declare succeeded without
        # producing something the human can look at. The Run page would
        # render as "completed ✅" with an empty diff, no artifacts, no
        # PR — i.e. the hallucinated-completion failure mode. Reject up
        # front so the agent has a chance to correct course (commit
        # something, register an artifact, or declare blocked instead).
        if outcome_enum == RunOutcome.SUCCEEDED:
            empty_diff = not (r.diff_stat or "").strip()
            empty_artifacts = not _parse_artifacts(r.artifacts_json)
            no_pr_on_task = True
            if r.task_id:
                from backend.models import Task as _Task
                task_for_pr = db.get(_Task, r.task_id)
                no_pr_on_task = not (task_for_pr and (task_for_pr.pr_url or "").strip())
            if empty_diff and empty_artifacts and no_pr_on_task:
                return {
                    "ok": False,
                    "error": (
                        "Cannot declare outcome=\"succeeded\" with no "
                        "deliverable. Either:\n"
                        "  1. Commit your changes (the Run's Changes tab "
                        "reads from git diff — empty diff means the "
                        "human sees nothing).\n"
                        "  2. Call register_run_artifact with at least "
                        "one URL / file path / PR link.\n"
                        "  3. If you don't have a deliverable, call "
                        "finish_run(outcome=\"blocked\") with a real "
                        "explanation in summary."
                    ),
                    "missing": {
                        "diff": empty_diff,
                        "artifacts": empty_artifacts,
                        "pr": no_pr_on_task,
                    },
                }
        r.outcome = outcome_enum
        if summary:
            r.summary = summary
        db.commit()

        # Post a comment back to the linked task so the human reading
        # the task feed sees the agent's verdict + summary. Without
        # this, finish_run was invisible from the task view.
        if r.task_id:
            try:
                from backend.models import Task as _Task, Activity as _Activity, Profile as _Profile
                task = db.get(_Task, r.task_id)
                if task:
                    icon = {
                        RunOutcome.SUCCEEDED: "✅",
                        RunOutcome.BLOCKED: "⛔",
                        RunOutcome.NEEDS_INPUT: "❓",
                        RunOutcome.FAILED: "❌",
                    }.get(outcome_enum, "•")
                    actor_name = ""
                    if r.agent_id:
                        agent = db.get(Agent, r.agent_id)
                        if agent and agent.profile_id:
                            prof = db.get(_Profile, agent.profile_id)
                            if prof:
                                actor_name = prof.name
                    comment_body = (
                        f"{icon} **Run {outcome_enum.value}** "
                        f"([run {r.id[:8]}](/forge/runs/{r.id}))\n\n"
                        f"{summary or '(no summary provided)'}"
                    )
                    db.add(_Activity(
                        project_id=task.project_id,
                        task_id=task.id,
                        actor=actor_name or "agent",
                        action="commented",
                        detail=comment_body,
                    ))
                    db.commit()
            except Exception as exc:  # noqa: BLE001 — best-effort
                # Don't fail the agent's finish_run because the side-effect
                # comment couldn't be posted; just print so it shows in logs.
                print(f"[finish_run] task-comment failed: {exc}")

        # AP-36: an agent that declares blocked or needs_input is asking
        # for human attention — notify admins so the dashboard surfaces it
        # instead of leaving it buried in the run history. Succeeded /
        # failed don't notify here: succeeded is routine, failed already
        # has its own run-complete notification path.
        if outcome_enum in (RunOutcome.BLOCKED, RunOutcome.NEEDS_INPUT):
            try:
                from backend.models import Task as _Task
                task_label = ""
                link = f"/forge/runs/{r.id}"
                if r.task_id:
                    task = db.get(_Task, r.task_id)
                    if task:
                        task_label = f" {task.key}" if task.key else ""
                        link = f"/projects/{task.project_id}/tasks/{task.id}"
                verb = ("blocked" if outcome_enum is RunOutcome.BLOCKED
                        else "needs input on")
                title = (f"Agent {verb} task{task_label}: "
                         f"{(summary or '').strip()[:140]}")
                _notify_admins(
                    db,
                    type_=f"agent.{outcome_enum.value}",
                    title=title,
                    link=link,
                )
                db.commit()
            except Exception as exc:  # noqa: BLE001 — best-effort
                print(f"[finish_run] notify-admins failed: {exc}")

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
    # Pick up the scope_key stashed at dispatch time so assistant/tool
    # messages land in the same conversation as the user prompt that
    # triggered them. Falls back to the trace's first message scope if
    # the in-memory map evaporated (backend restart mid-stream).
    scope = _TRACE_SCOPE.get(trace_id) or ""
    with _session() as db:
        if not scope:
            existing = (db.query(AgentMessage)
                          .filter(AgentMessage.trace_id == trace_id,
                                  AgentMessage.scope_key.isnot(None))
                          .first())
            scope = (existing.scope_key if existing else "") or ""
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
                scope_key=scope or None,
                role=role,
                content=content,
                tool_name=tool_name,
                tool_input=json.dumps(evt.get("input")) if evt.get("input") is not None else None,
                tool_output=evt.get("output") if evt_type == "tool_result" else None,
                model_used=evt.get("model", ""),
            ))
        db.commit()
        return {"ok": True, "count": len(events)}


def mark_dispatch_dropped(*, agent_id: str, trace_id: str,
                          run_id: str | None) -> None:
    """Surface a dispatch that died silently because no daemon was online.

    Writes a SYSTEM message to the chat thread so the user can see in the
    UI what went wrong, and fails the Run row if one was created. Without
    this the user just sees their message hang forever with no signal.
    """
    msg = (
        "⚠ No daemon online — your message couldn't be delivered. "
        "Start the daemon (`agentira daemon start --foreground`) and try again."
    )
    with _session() as db:
        # Mark the run failed if we have one
        if run_id:
            r = db.query(Run).filter(Run.id == run_id).first()
            if r and r.status in (RunStatus.PENDING, RunStatus.RUNNING):
                r.status = RunStatus.FAILED
                r.error = "Daemon offline at dispatch — silent drop avoided"
                r.finished_at = datetime.now(timezone.utc)
        # Drop a SYSTEM message tagged with this trace so the chat UI
        # picks it up via the existing poll. It MUST carry the scope_key:
        # the chat filters by scope and shows a "thinking…" spinner while
        # the last in-scope message is the user's — a scopeless failure
        # message never lands in the thread and the spinner spins forever.
        # Recover the scope from the in-memory trace map (set at dispatch),
        # falling back to the persisted user message under this trace.
        scope = _TRACE_SCOPE.pop(trace_id, "")
        if not scope:
            m = (db.query(AgentMessage)
                   .filter(AgentMessage.trace_id == trace_id,
                           AgentMessage.scope_key.isnot(None),
                           AgentMessage.scope_key != "")
                   .order_by(AgentMessage.created_at.desc())
                   .first())
            if m:
                scope = m.scope_key
        db.add(AgentMessage(
            agent_id=agent_id,
            run_id=run_id,
            trace_id=trace_id,
            scope_key=scope or None,
            role=MessageRole.SYSTEM,
            content=msg,
        ))
        db.commit()


# A run whose claude subprocess died abnormally — non-zero exit, no
# agent verdict — is usually a transient crash (an API blip, a
# claude-code hiccup at a turn boundary), not a real failure. Auto-retry
# it a couple of times, resuming the conversation, before giving up.
# The caps stop a retry storm on a genuinely broken task.
_AUTO_RETRY_MAX = 2
_AUTO_RETRY_WINDOW_MIN = 20


def _maybe_auto_retry(run_id: str, error: str) -> bool:
    """If `run_id` failed from a transient subprocess crash, re-dispatch
    its task (the scope's session is reused, so the agent continues where
    it left off) up to `_AUTO_RETRY_MAX` times. Returns True if a retry
    was dispatched."""
    from datetime import timedelta
    if "subprocess exited with code" not in (error or ""):
        return False  # not the transient-crash signature
    with _session() as db:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run or not run.task_id or not run.agent_id:
            return False
        task_id, agent_id = run.task_id, run.agent_id
        cutoff = datetime.now(timezone.utc) - timedelta(
            minutes=_AUTO_RETRY_WINDOW_MIN)
        failed = (db.query(Run)
                    .filter(Run.task_id == task_id,
                            Run.agent_id == agent_id,
                            Run.status == RunStatus.FAILED,
                            Run.created_at >= cutoff)
                    .count())
    # `failed` counts the run that just failed too — so allow retries
    # while we've failed at most _AUTO_RETRY_MAX times.
    if failed > _AUTO_RETRY_MAX:
        _dispatch_logger.warning(
            "Auto-retry exhausted task=%s agent=%s (%d recent fails)",
            task_id, agent_id, failed)
        return False
    result = schedule_task_run(task_id=task_id, agent_id=agent_id)
    if result.get("error"):
        _dispatch_logger.warning("Auto-retry dispatch failed task=%s: %s",
                                 task_id, result["error"])
        return False
    _dispatch_logger.info("Auto-retried crashed run=%s task=%s (attempt %d)",
                          run_id, task_id, failed + 1)
    return True


def complete_trigger(agent_id: str, *, trace_id: str, run_id: str | None,
                     success: bool, input_tokens: int = 0, output_tokens: int = 0,
                     error: str | None = None,
                     diff_stat: str = "", diff: str = "",
                     session_id: str = "", workdir: str = "",
                     paused: bool = False,
                     cancelled: bool = False,
                     diagnostics: dict | None = None,
                     materialize_reason: str = "",
                     session_lost: bool = False,
                     work_signal: dict | None = None) -> dict:
    """Finalize a trigger. Updates the Run if `run_id` is set; for chat
    triggers we still surface the failure as a system-role message on
    the agent so the chat UI shows what actually went wrong instead of
    sitting silent forever."""
    logger_msg = (f"complete_trigger trace={trace_id} agent={agent_id} "
                  f"run={run_id or '-'} ok={success} tokens={input_tokens}/{output_tokens}")

    # AP-133: daemon flagged that the stamped session_id wasn't on disk
    # locally; it retried without --resume. Clear the stale id from the
    # scope's Conversation row so the NEXT dispatch doesn't reuse it and
    # land in the same broken state. Also drop a chat-thread system
    # message so the user knows what happened. Runs unconditionally —
    # cancelled / paused / normal completions all benefit.
    if session_lost:
        scope = _TRACE_SCOPE.get(trace_id) or ""
        if not scope:
            with _session() as db:
                m = (db.query(AgentMessage)
                       .filter(AgentMessage.trace_id == trace_id,
                               AgentMessage.scope_key.isnot(None),
                               AgentMessage.scope_key != "")
                       .order_by(AgentMessage.created_at.desc())
                       .first())
                if m:
                    scope = m.scope_key
        if scope:
            with _session() as db:
                conv = (db.query(Conversation)
                          .filter(Conversation.agent_id == agent_id,
                                  Conversation.scope_key == scope)
                          .first())
                if conv:
                    conv.runtime_session_id = ""
                db.add(AgentMessage(
                    agent_id=agent_id, run_id=run_id, trace_id=trace_id,
                    scope_key=scope, role=MessageRole.SYSTEM,
                    content=("ℹ Previous claude session wasn't found on "
                             "this daemon — resumed from conversation "
                             "history instead."),
                ))
                db.commit()

    # P1 cancel path: the daemon confirmed it killed the subprocess in
    # response to a user-initiated cancel. Flip the run to CANCELLED. We
    # deliberately do NOT post the "⚠ execution failed" system message or
    # notify admins of a failure — the user asked for this, it's not a
    # bug. Symmetric with the `paused` branch below.
    if cancelled and run_id:
        with _session() as db:
            r = db.query(Run).filter(Run.id == run_id).first()
            if r:
                r.status = RunStatus.CANCELLED
                _broadcast_status(run_id, RunStatus.CANCELLED, r.outcome)
                # Clear the audit timestamp/intent so the reconciler stops
                # treating INTERRUPTING as a stuck transient.
                r.stop_requested_at = None
                r.interrupt_intent = None
                r.finished_at = datetime.now(timezone.utc)
                if r.outcome is None:
                    r.outcome = RunOutcome.FAILED  # for the verdict badge
                if r.summary is None:
                    r.summary = "Run cancelled by user."
                r.input_tokens = (r.input_tokens or 0) + input_tokens
                r.output_tokens = (r.output_tokens or 0) + output_tokens
                if workdir:
                    r.workdir = workdir
                if session_id:
                    # Mirror the success-path persist: cancelled runs are
                    # still worth a session pointer for post-mortem.
                    r.session_id = session_id
                if diff_stat:
                    r.diff_stat = diff_stat
                if diff:
                    r.diff = diff
                if materialize_reason:
                    r.materialize_reason = materialize_reason
                db.commit()
        _TRACE_SCOPE.pop(trace_id, None)
        # Discarded is terminal — a message queued behind this run still runs.
        from backend.forge import msg_queue as _mq
        _mq.flush_next(agent_id, run_id=run_id)
        cleanup = _worktree_cleanup_hint(run_id)
        return {"ok": True, "trace_id": trace_id, "cancelled": True,
                "logged": logger_msg + " [cancelled — no admin notify]",
                "cleanup_worktree": cleanup["path"],
                "cleanup_branch": cleanup["branch"]}

    # Pause path: the daemon parked the run (SIGTERM'd the subprocess) and
    # posts back ONLY to hand us the session_id. The run stays PAUSED —
    # no completion, no failure, no chat message. Persist the session so
    # resume_run can relaunch with `claude --resume`.
    if paused:
        scope = _TRACE_SCOPE.pop(trace_id, "")
        if not scope:
            with _session() as db:
                m = (db.query(AgentMessage)
                       .filter(AgentMessage.trace_id == trace_id,
                               AgentMessage.scope_key.isnot(None),
                               AgentMessage.scope_key != "")
                       .order_by(AgentMessage.created_at.desc())
                       .first())
                if m:
                    scope = m.scope_key
        if session_id and scope:
            upsert_conversation(agent_id=agent_id, scope_key=scope,
                                runtime_session_id=session_id)
        # Flip INTERRUPTING → PAUSED unconditionally on the daemon's ack.
        # Even if no session_id arrived (non-claude runtimes), the daemon
        # confirmed the kill — that's the signal we were waiting for. PAUSED
        # is not terminal (the user resumes), so the message queue is NOT
        # flushed here — a queued message waits until the run actually ends.
        if run_id:
            with _session() as db:
                r = db.query(Run).filter(Run.id == run_id).first()
                if r:
                    if session_id:
                        r.session_id = session_id
                    if materialize_reason:
                        r.materialize_reason = materialize_reason
                    if r.status == RunStatus.INTERRUPTING:
                        r.status = RunStatus.PAUSED
                        r.stop_requested_at = None
                        r.interrupt_intent = None
                        _broadcast_status(run_id, RunStatus.PAUSED)
                    db.commit()
        return {"ok": True, "trace_id": trace_id, "paused": True,
                "logged": logger_msg + " [paused — session persisted]"}

    # AP-108: the agent's explicit finish_run verdict outranks the process
    # exit code. If the agent already declared an outcome, its work is done
    # — a non-zero subprocess exit afterward (a SIGTERM from a pause, or
    # claude's own session-teardown noise) must NOT flip the run to FAILED.
    # `status` only tracks process lifecycle; `outcome` carries the verdict.
    agent_declared_outcome = None
    if run_id:
        with _session() as db:
            _r = db.query(Run).filter(Run.id == run_id).first()
            agent_declared_outcome = _r.outcome if _r else None
    effective_success = success or (agent_declared_outcome is not None)
    if effective_success and not success:
        logger_msg += (f" [process exited non-zero but agent declared "
                       f"outcome={agent_declared_outcome.value}; "
                       f"treating run as completed]")

    if run_id:
        complete_run(
            run_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error=error if not effective_success else None,
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
                if workdir:
                    r.workdir = workdir
                if session_id:
                    # Persist on the Run row too (not just the Conversation
                    # via upsert_conversation below). The Run page renders
                    # this to point the user at ~/.claude/projects/<enc>/
                    # <session>.jsonl. Without it the diagnostic strip
                    # shows "—" even when a session was captured.
                    r.session_id = session_id
                if diagnostics:
                    # AP-107: cap the persisted blob so a runaway stderr can't
                    # bloat the row. The spec budgets ~50KB total.
                    r.diagnostics_json = _trim_diagnostics_json(diagnostics)
                if materialize_reason:
                    r.materialize_reason = materialize_reason
                db.commit()

    # Persist conversation continuity. Look up the scope this trace was
    # dispatched under; upsert the runtime session handle. Always bumps
    # last_used_at even when session_id is empty (proves the conversation
    # existed). Empty session_id won't clobber a previously-stored good one.
    scope = _TRACE_SCOPE.pop(trace_id, "")
    if scope:
        # Refresh the conversation's rolling summary from the run's own
        # finish_run summary (cheap, no LLM) so assemble_context can carry
        # context past the token budget instead of dropping it.
        roll = None
        if run_id:
            with _session() as db:
                _r = db.query(Run).filter(Run.id == run_id).first()
                if _r and _r.summary:
                    roll = _r.summary.strip() or None
        upsert_conversation(
            agent_id=agent_id, scope_key=scope,
            runtime_session_id=session_id or "",
            rolling_summary=roll,
            rolling_summary_through_run_id=run_id if roll else None,
        )

    # Run emergence — a chat turn that produced durable work surfaces as a Run
    # (is_work=True); a talk-only turn stays chat. Owned by the runs module.
    if run_id:
        from backend.forge import runs as _runs
        if _runs.mark_is_work_if_any(
                run_id, work_signal=work_signal,
                has_explicit_outcome=agent_declared_outcome is not None):
            _dispatch_logger.info(
                "chat turn produced work trace=%s run=%s — surfaced as a Run",
                trace_id, run_id)

    # Failure surfacing — the daemon already logs server-side, but the
    # human in the UI only sees what's in the chat thread. Drop a
    # system-role message tagged with this trace so the existing chat
    # poll picks it up.
    #
    # It MUST carry the scope_key: the chat UI filters messages by scope
    # and shows a "thinking…" spinner while the last message in the scope
    # is the user's. A failure message with scope_key=None never lands in
    # the thread, so the spinner spins forever. `scope` may be empty if
    # the backend restarted and lost _TRACE_SCOPE — recover it from the
    # messages already persisted under this trace.
    #
    # AP-108: suppressed when the agent declared an outcome — a non-zero
    # exit after a clean finish_run is not a failure the user needs to see.
    retried = False
    if not effective_success and error:
        # A transient subprocess crash auto-retries (resuming the
        # session) instead of surfacing a hard failure to the user.
        if run_id:
            try:
                retried = _maybe_auto_retry(run_id, error)
            except Exception as exc:  # noqa: BLE001 — best-effort
                _dispatch_logger.warning("auto-retry raised: %s", exc)
        fail_scope = scope
        if not fail_scope:
            with _session() as db:
                m = (db.query(AgentMessage)
                       .filter(AgentMessage.trace_id == trace_id,
                               AgentMessage.scope_key.isnot(None),
                               AgentMessage.scope_key != "")
                       .order_by(AgentMessage.created_at.desc())
                       .first())
                if m:
                    fail_scope = m.scope_key
        with _session() as db:
            db.add(AgentMessage(
                agent_id=agent_id,
                run_id=run_id,
                trace_id=trace_id,
                scope_key=fail_scope or None,
                role=MessageRole.SYSTEM,
                content=("↻ Run crashed mid-step (transient) — auto-retrying; "
                         "the agent resumes where it left off."
                         if retried
                         else f"⚠ Agent execution failed: {error[:600]}"),
            ))
            db.commit()

    # Completed / failed is terminal and the conversation is now idle — flush
    # the next queued message (if any) as the following turn. PAUSED returns
    # earlier and skips this (the user resumes; the queue waits).
    from backend.forge import msg_queue as _mq
    _mq.flush_next(agent_id, scope_key=scope, run_id=run_id)

    # AP-123: tell the daemon to tear down the per-run worktree on the
    # terminal completion path. PAUSED branches return earlier and skip
    # this — they need the worktree intact for resume. Best-effort: the
    # daemon ignores cleanup when worktree_path is empty.
    cleanup = _worktree_cleanup_hint(run_id)
    return {"ok": True, "trace_id": trace_id, "logged": logger_msg,
            "auto_retried": retried,
            "cleanup_worktree": cleanup["path"],
            "cleanup_branch": cleanup["branch"]}


def _worktree_cleanup_hint(run_id: str | None) -> dict:
    """ADR 009: the (agent, task) worktree is the conversation home and
    must survive for the life of the task — it's reused by every run and
    chat in the task so the agent's working files persist and claude
    `--resume` keeps landing in one stable cwd. So a terminal run NEVER
    tears it down: we always return empty hints (the daemon's cleanup is
    guarded by `if cw and cb`, so empty = no-op). Worktree teardown moves
    to a task archive/delete hook (AP-134 A4), the only place it's safe.

    `run_id` is kept in the signature for the call sites that still pass
    it; the value is ignored on purpose."""
    return {"path": "", "branch": ""}


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
    scope_key: str | None = None,
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
    # ADR 008: sending a message into a task scope whose Run is PAUSED
    # auto-resumes the run. The user's message IS the continuation turn —
    # it's dispatched below carrying the scope's resume session, so the
    # agent picks up via claude --resume. We only need to flip the run
    # PAUSED → RUNNING here; we must NOT call resume_run(), which would
    # dispatch its own continuation nudge and double-run. A flag is
    # returned so the UI can show a "Resumed paused run" badge.
    resumed_run_id = None
    if scope_key and scope_key.startswith("task:"):
        task_id = scope_key.split(":", 1)[1]
        with _session() as db:
            # A stop in flight wins. If the daemon hasn't confirmed the
            # INTERRUPTING kill yet, sending a message would race it (and on
            # success would silently spawn a second proc). Refuse cleanly so
            # the user retries once the dust settles.
            in_flight_stop = (db.query(Run)
                              .filter(Run.task_id == task_id,
                                      Run.agent_id == agent_id,
                                      Run.status == RunStatus.INTERRUPTING)
                              .first())
            if in_flight_stop:
                return {"error": (f"Run is {in_flight_stop.status.value}; "
                                  "wait for the stop to confirm before "
                                  "sending another message.")}
            # Chat-during-run: a message into a RUNNING turn is QUEUED, not
            # steered. The active turn runs to completion uninterrupted; the
            # queued message dispatches FIFO when the turn reaches a terminal
            # state (msg_queue.flush_next, called from complete_trigger). A
            # conversation is single-threaded, so this preserves order without
            # interrupting work. Return early — no fresh turn dispatched now.
            active = (db.query(Run)
                        .filter(Run.task_id == task_id,
                                Run.agent_id == agent_id,
                                Run.status == RunStatus.RUNNING)
                        .order_by(Run.created_at.desc())
                        .first())
            if active:
                from backend.forge import msg_queue
                queued_id = msg_queue.enqueue(
                    agent_id=agent_id, scope_key=scope_key,
                    content=content, user_context=user_context)
                return {"ok": True, "queued_id": queued_id,
                        "note": "queued — the current turn is still running"}

            # PAUSED, or parked-by-outcome (needs_input / blocked) and still
            # the latest activity → resume THIS run with the user's message as
            # the next turn (same run_id, so it continues the episode rather
            # than crystallizing a new run). resumed_run_id is threaded onto
            # the dispatch below so complete_trigger updates this run.
            paused = (db.query(Run)
                        .filter(Run.task_id == task_id,
                                Run.agent_id == agent_id,
                                Run.status == RunStatus.PAUSED)
                        .order_by(Run.created_at.desc())
                        .first())
            if not paused:
                parked = (db.query(Run)
                            .filter(Run.task_id == task_id,
                                    Run.agent_id == agent_id,
                                    Run.outcome.in_([RunOutcome.NEEDS_INPUT,
                                                     RunOutcome.BLOCKED]))
                            .order_by(Run.created_at.desc())
                            .first())
                if parked:
                    newer = (db.query(Run)
                               .filter(Run.task_id == task_id,
                                       Run.agent_id == agent_id,
                                       Run.created_at > parked.created_at)
                               .count())
                    if newer == 0:
                        paused = parked  # revive the parked run
            if paused:
                resumed_run_id = paused.id
                # PAUSED/parked are confirmed-terminated (no live proc to
                # race), so flip straight to RUNNING. Clear the parked
                # verdict — the agent re-declares one when it finishes.
                paused.status = RunStatus.RUNNING
                paused.outcome = None
                db.commit()
                _broadcast_status(paused.id, RunStatus.RUNNING)

    # A message into a task whose last run failed is just a chat turn — we do
    # NOT auto-schedule a retry run. Auto-retry turned plain comments/chats into
    # full task.scheduled runs (and the explicit-run is_work=True stamp made a
    # talk-only reply look like work). Retrying a failed run is now an explicit
    # action (the Retry button on the run). Chat falls through to a chat turn.

    with _session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        if not a:
            return {"error": "Agent not found"}
        if a.runtime_id:
            # AP-86/87: auto-injected MCP servers (agentira, memory) ride on
            # every dispatch regardless of project. Project-bound chats also
            # resolve repo_path + conventions; free-form chats just get the
            # default toolset and screen context.
            from backend.forge.mcp_registry import build_mcp_config
            from backend.models import Project, Profile
            repo_path = ""
            conventions_md = ""
            ctx = user_context if isinstance(user_context, dict) else {}
            project_id = ctx.get("project_id")
            # AP-105 / ADR 008: when continuing a task- or run-scoped
            # conversation, the project comes from the Task/Run row (the
            # agent worked there), NOT from the user's current screen —
            # user might be elsewhere now but still chatting in that scope.
            # Without this, cwd would resolve to the wrong worktree and
            # claude's session handle would fail to resume.
            if scope_key and scope_key.startswith("task:"):
                from backend.models import Task
                _task_id = scope_key.split(":", 1)[1]
                _task = db.query(Task).filter(Task.id == _task_id).first()
                if _task and _task.project_id:
                    project_id = _task.project_id
            elif scope_key and scope_key.startswith("run:"):
                _run_id = scope_key.split(":", 1)[1]
                _run = db.query(Run).filter(Run.id == _run_id).first()
                if _run and _run.project_id:
                    project_id = _run.project_id
            proj = db.get(Project, project_id) if project_id else None
            if proj:
                conventions_md = proj.conventions_md or ""

            agent_prof = db.get(Profile, a.profile_id) if a.profile_id else None
            # cwd is a template (`~/...`); daemon expands and ensures the
            # dir + git worktree. Backend can't touch the host filesystem.
            if proj:
                worktree_source_path = proj.repo_path or ""
                worktree_source_url = getattr(proj, "repo_url", None) or ""
                # Task-scoped chats share cwd with the task's runs so
                # claude --resume works across run/chat boundaries.
                _task_id_for_cwd = None
                if scope_key and scope_key.startswith("task:"):
                    _task_id_for_cwd = scope_key.split(":", 1)[1]
                task_path, task_branch = _compute_worktree_paths(
                    agent_id=a.id, project_id=project_id,
                    task_id=_task_id_for_cwd,
                )
                if task_path:
                    repo_path = task_path
                    worktree_branch = task_branch
                else:
                    repo_path = ensure_agent_worktree(a, proj)
                    worktree_branch = f"agent/{a.id}/work"
            else:
                repo_path = ensure_agent_home_dir(a)
                worktree_source_path = ""
                worktree_source_url = ""
                worktree_branch = ""

            # Bake the AGENT's own api_key into the agentira MCP entry so
            # tool calls authenticate as the agent (visible in audit).
            home_path_for_memory = (
                (agent_prof.home_path if agent_prof else None)
                or resolve_agent_home(a)
            )
            cfg = build_mcp_config(
                agent_mcp_servers=json.loads(a.mcp_servers) if a.mcp_servers else None,
                agent_id=a.id,
                project_id=project_id,
                agent_api_key=(agent_prof.api_key if agent_prof else None),
                mcp_config_override=(agent_prof.mcp_config_override if agent_prof else None),
                disabled_servers=(json.loads(agent_prof.mcp_disabled) if (agent_prof and agent_prof.mcp_disabled) else None),
                agent_home_path=home_path_for_memory,
                repo_path=repo_path if proj else None,
            )
            mcp_config_json = json.dumps(cfg) if cfg else ""
            mcp_strict = bool(agent_prof.mcp_strict) if agent_prof else False

            # Conversation continuity: scope-key tells us WHICH conversation
            # this chat belongs to (per-project, default, etc.). For runtimes
            # that support resume (claude), pass the session handle on the
            # frame. For gateway runtimes (openclaw/ollama, no resume), the
            # daemon will see no session_id and the gateway path rebuilds
            # history from forge_messages on its own.
            # AP-105: scope_key from caller wins (user explicitly continuing
            # a specific conversation, e.g. a run-scoped chat after the run
            # completed). Otherwise derive from project_id.
            if scope_key:
                scope = scope_key
            elif run_id:
                # ADR 008: if dispatching against a run, the scope is the
                # parent task so re-runs share memory. Resolve task from run.
                _run = db.query(Run).filter(Run.id == run_id).first()
                _task_id = _run.task_id if _run else None
                scope = conversation_scope_key(task_id=_task_id, project_id=project_id)
            else:
                scope = conversation_scope_key(project_id=project_id)
            rt = a.runtime
            caps = (json.loads(rt.capabilities) if (rt and rt.capabilities) else [])
            resume_id = ""
            if "resume" in caps:
                resume_id = get_runtime_session(agent_id=a.id, scope_key=scope)
            # One context path: native resume short-circuits; otherwise rebuild
            # a token-budgeted history. When the runtime claims resume but the
            # session was lost (resume_id empty), we still fall back to rebuild
            # instead of dropping the agent's context.
            prompt_with_history = assemble_context(
                agent_id=a.id, scope_key=scope, current=content,
                native_resume_available=bool(resume_id),
            )

            # Serialize chats per (agent, scope). Two claude subprocesses
            # sharing one cwd corrupt each other's index; the older one
            # also keeps running invisibly because the UI only knows
            # about the latest trace. Cancel any prior in-flight trace
            # for this scope before spawning a new one.
            _runtime_id_for_cancel = a.runtime_id
            _prior_traces = [tid for tid, sc in list(_TRACE_SCOPE.items())
                             if sc == scope]
            if _prior_traces:
                from backend.forge.ws_dispatch import hub as _hub
                for _tid in _prior_traces:
                    try:
                        _dispatch_coro(_hub.dispatch_cancel(
                            runtime_id=_runtime_id_for_cancel,
                            trace_id=_tid,
                            scope_key=scope,
                        ))
                    except Exception:
                        pass
                    _TRACE_SCOPE.pop(_tid, None)

            result = dispatch_trigger(
                # ADR 009 / D: when resuming a run, the turn carries its
                # run_id so complete_trigger updates THAT run (and C1 won't
                # crystallize a duplicate). Plain chat turns stay run-less.
                agent_id, prompt_with_history,
                run_id=run_id or resumed_run_id, kind="chat",
                repo_path=repo_path,
                worktree_source_path=worktree_source_path,
                worktree_source_url=worktree_source_url,
                worktree_branch=worktree_branch,
                conventions_md=conventions_md,
                mcp_config_json=mcp_config_json,
                mcp_strict=mcp_strict,
                user_context=user_context,
                resume_session_id=resume_id,
                scope_key=scope,
            )
            if resumed_run_id and isinstance(result, dict):
                result["resumed_run_id"] = resumed_run_id
            return result

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


