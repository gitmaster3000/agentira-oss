"""Forge domain models — Agents, Runtimes, and Runs."""

import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String, Text, Integer, Float, DateTime, Boolean,
    ForeignKey, Enum as SAEnum, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Enums ────────────────────────────────────────────────────────────────

class AgentStatus(str, enum.Enum):
    ONLINE  = "online"
    OFFLINE = "offline"
    BUSY    = "busy"


class MessageRole(str, enum.Enum):
    USER      = "user"
    ASSISTANT = "assistant"
    SYSTEM    = "system"
    TOOL      = "tool"


class RunStatus(str, enum.Enum):
    # AP-112: READY = the Run is prepared (prompt persisted, agent assigned)
    # but the user hasn't pressed Start yet. Distinct from PENDING (queued
    # by the system, about to dispatch automatically) so the UI can show a
    # prompt-editor card without overloading PENDING's meaning.
    READY     = "ready"
    PENDING   = "pending"
    RUNNING   = "running"
    # Single transient state: the user clicked Stop or Discard; we've sent the
    # WS frame but the daemon hasn't acked yet. `Run.interrupt_intent`
    # ("pause"|"discard") decides where it lands — PAUSED or CANCELLED. The
    # daemon does the identical SIGTERM either way. UI shows "Stopping…".
    # (Replaces the old pausing/cancelling/resuming trio. Resume is just
    # paused → pending → running, so there is no separate resuming state.)
    INTERRUPTING = "interrupting"
    PAUSED    = "paused"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


class RunOutcome(str, enum.Enum):
    """Semantic verdict of a run, set by the agent via the finish_run MCP
    tool. Distinct from RunStatus, which tracks process lifecycle.

    A run can be status=COMPLETED + outcome=BLOCKED (process exited cleanly,
    but the agent says it can't proceed without external help). Both are
    meaningful and the UI shows outcome as the primary badge."""
    SUCCEEDED   = "succeeded"
    BLOCKED     = "blocked"
    NEEDS_INPUT = "needs_input"
    FAILED      = "failed"


# ── Runtime ──────────────────────────────────────────────────────────────

class RuntimeStatus(str, enum.Enum):
    ONLINE  = "online"
    OFFLINE = "offline"
    BUSY    = "busy"
    UNKNOWN = "unknown"


class ForgeRuntime(Base):
    """A CLI binary (or HTTP gateway) registered by a running daemon."""
    __tablename__ = "forge_runtimes"
    __table_args__ = (UniqueConstraint("daemon_id", "provider"),)

    id: Mapped[str]             = mapped_column(String(12), primary_key=True, default=_new_id)
    org_id: Mapped[str]         = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    daemon_id: Mapped[str]      = mapped_column(String(64), nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider: Mapped[str]       = mapped_column(String(40), nullable=False)
    binary_path: Mapped[str]    = mapped_column(String(500), nullable=False)
    version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[RuntimeStatus] = mapped_column(SAEnum(RuntimeStatus), default=RuntimeStatus.UNKNOWN)
    capabilities: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    models: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list — supported model ids
    # Host-side discovered tools the runtime brings on its own. JSON shape:
    # {"builtins": ["Read","Edit",...], "host_mcp_servers": [{"name":"slack","transport":"stdio"}, ...], "host_md_files": ["~/.claude/CLAUDE.md", ...]}
    # Daemon fills this at registration time so the UI can show Layer 1 + 2
    # alongside Agentira's Layer 3 picks. Best-effort; nullable.
    host_tools: Mapped[str | None] = mapped_column(Text, nullable=True)
    gateway_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gateway_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    agents: Mapped[list["Agent"]] = relationship(back_populates="runtime")


# ── Agent ────────────────────────────────────────────────────────────────

class Agent(Base):
    """A runtime executor — an agent instance that picks up and runs work."""
    __tablename__ = "forge_agents"

    id: Mapped[str]             = mapped_column(String(12), primary_key=True, default=_new_id)
    org_id: Mapped[str]         = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    profile_id: Mapped[str | None] = mapped_column(ForeignKey("profiles.id"), nullable=True)
    name: Mapped[str]           = mapped_column(String(120), nullable=False)
    executor_type: Mapped[str]  = mapped_column(String(30), default="http")
    model: Mapped[str]          = mapped_column(String(120), default="")
    status: Mapped[AgentStatus] = mapped_column(SAEnum(AgentStatus), default=AgentStatus.OFFLINE)
    webhook_url: Mapped[str]    = mapped_column(String(500), default="")
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_runs: Mapped[int]     = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    personality: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    runtime_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    runtime_gateway_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    runtime_hooks_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    runtime_agent_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    schedule_start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    schedule_end: Mapped[str | None] = mapped_column(String(10), nullable=True)
    schedule_tz: Mapped[str | None] = mapped_column(String(40), nullable=True)
    schedule_days: Mapped[str | None] = mapped_column(String(60), nullable=True)
    schedule_enabled: Mapped[bool] = mapped_column(default=False)
    schedule_cron: Mapped[str | None] = mapped_column(String(60), nullable=True)
    runtime_id: Mapped[str | None] = mapped_column(ForeignKey("forge_runtimes.id"), nullable=True)
    # Default project this agent works in. UX-only: when set, chat surfaces
    # use it as the default project_id in user_context so the user doesn't
    # have to pick every time. Per-call user_context still wins — AP-76's
    # plumbing isn't replaced. This is a default, not a constraint.
    default_project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    # JSON list of MCP server names from backend.forge.mcp_registry.REGISTRY.
    # Excludes auto-injected servers (agentira, memory) — those are added
    # at dispatch by build_mcp_config regardless of this list.
    mcp_servers: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    profile = relationship("Profile")
    runtime: Mapped["ForgeRuntime | None"] = relationship(back_populates="agents")
    runs: Mapped[list["Run"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    messages: Mapped[list["AgentMessage"]] = relationship(back_populates="agent", cascade="all, delete-orphan")


# ── Run ──────────────────────────────────────────────────────────────────

class Run(Base):
    """A single execution — one webhook trigger → one traceable run."""
    __tablename__ = "forge_runs"

    id: Mapped[str]             = mapped_column(String(12), primary_key=True, default=_new_id)
    agent_id: Mapped[str]       = mapped_column(ForeignKey("forge_agents.id"), nullable=False)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)

    trigger_event: Mapped[str]  = mapped_column(String(60), default="")
    status: Mapped[RunStatus]   = mapped_column(SAEnum(RunStatus), default=RunStatus.PENDING)
    model_used: Mapped[str]     = mapped_column(String(120), default="")

    started_at: Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None]      = mapped_column(Integer, nullable=True)

    input_tokens: Mapped[int]   = mapped_column(Integer, default=0)
    output_tokens: Mapped[int]  = mapped_column(Integer, default=0)
    cost_usd: Mapped[float]     = mapped_column(Float, default=0.0)
    error: Mapped[str | None]   = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    workdir: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # outcome: agent-declared semantic result (set by finish_run MCP tool).
    # summary: one-paragraph human-readable result (also from finish_run).
    outcome: Mapped[RunOutcome | None] = mapped_column(SAEnum(RunOutcome), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Captured by the daemon when the run's workdir is a git repo. diff_stat
    # is the human-readable `git diff --stat` summary; diff is the full patch
    # capped at ~50KB to keep DB rows reasonable. Both null when not a repo
    # or when nothing changed.
    diff_stat: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AP-112: prompt persisted at prepare time so the user can edit it on
    # the RunDetail page before clicking Start. Auto-dispatched runs also
    # store it so the prompt is grep-able after the fact.
    initial_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AP-107: post-mortem bundle captured by the daemon at run-end. JSON
    # blob: {exit_code, stderr_tail, last_events_tail, captured_at}. Surfaced
    # via the get_run_diagnostics MCP tool for run-investigation flows.
    diagnostics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When did the user click Stop / Discard? Set the moment INTERRUPTING is
    # entered; cleared on confirmation. The reconciler reads this to escalate
    # a stuck INTERRUPTING row (daemon dropped the frame).
    stop_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Why we're INTERRUPTING: "pause" (Stop — preserve session, resumable) or
    # "discard" (Discard — throw the run away). Decides the terminal state the
    # daemon ack / reconciler resolves to (PAUSED vs CANCELLED). NULL otherwise.
    interrupt_intent: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # CLEANUP(AP-190): drop this column. A Run is one-per-(agent,task) — the
    # work-view of that task's chat — so there's no per-turn "is this work?"
    # flag to gate visibility. Needs a migration to drop forge_runs.is_work.
    # is_work: did this run produce durable work (a diff / artifacts / an
    # agent-declared outcome)? Set at completion from the work predicate.
    # Only is_work runs surface in the Runs list / dashboard — a pure-chat
    # turn is a run row with is_work=False that the UI never shows as a "Run".
    # Replaces the old shadow create-then-delete/promote dance.
    is_work: Mapped[bool] = mapped_column(default=False)
    # Per-run liveness clock, refreshed from the daemon's inflight heartbeat
    # report. The reconciler flips a non-terminal run to FAILED when this goes
    # stale — even if the daemon itself is still alive (dead-dispatch case).
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # AP-125: structured artifacts the agent produced during the run.
    # JSON list of {"url": str, "label": str, "kind": str}. Surfaces in
    # the Run dict so the UI can render "Here's what got built" links
    # without scraping the chat transcript. Set via the register_run_
    # artifact MCP tool from inside the agent.
    artifacts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AP-123: per-run git worktree. Every run gets its own isolated
    # working tree + branch so concurrent runs of the same agent don't
    # scribble over each other's index. The daemon materializes the
    # worktree at dispatch (git worktree add) and removes it on terminal
    # complete (cleanup_worktree=True). PAUSED runs keep theirs so
    # resume can re-enter. NULL on legacy rows — cleanup is a no-op.
    worktree_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    worktree_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Diagnostic flag from the daemon's materializer. "ok" when the
    # frame's repo_path resolved and the agent ran inside the repo;
    # "no_repo_path" when no repo was attached; "repo_path_not_found:..."
    # when the stamped path didn't exist on the daemon host (silent
    # empty-scratch-dir failure mode). Surfaced on the Run page so the
    # user knows immediately why a run "did nothing".
    materialize_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Per-run log directory on the daemon host. Contains:
    #   stdout.log  — full claude stream-json output, lossless
    #   stderr.log  — full claude stderr
    #   meta.json   — cwd, branch, session_id, materialize_reason at end
    # Path is tilde-prefixed; daemon expanduser's at use time. NULL on
    # legacy rows or for runs prepared before this column landed.
    log_dir: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # AP-297: cached pre-run (ready) checks. Recomputed when the cache is
    # older than the project's TTL or when the operational-env signature
    # changes (runtime, daemon online, API key, env vars, MCP, repo) — never
    # for task-content edits. Keeps re-validation meaningful without re-running
    # the checks on every on-ready fetch of a reused run.
    ready_checks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ready_checks_sig: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ready_checks_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="runs")
    task = relationship("Task")
    project = relationship("Project")


# ── AgentMessage ────────────────────────────────────────────────────────

class AgentMessage(Base):
    """A single message in an agent's chat history."""
    __tablename__ = "forge_messages"

    id: Mapped[str]             = mapped_column(String(12), primary_key=True, default=_new_id)
    agent_id: Mapped[str]       = mapped_column(ForeignKey("forge_agents.id"), nullable=False)
    run_id: Mapped[str | None]  = mapped_column(String(12), nullable=True)
    # trace_id: ephemeral trigger id linking user prompt → assistant reply(s).
    # Persisted as a Trigger row in a future increment; today it's just a
    # correlation handle for grepping logs and grouping messages per turn.
    trace_id: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    # scope_key: which conversation this message belongs to. See
    # services.conversation_scope_key for the scheme (run:<id>,
    # chat:project:<pid>, chat:default). Used by gateway runtimes that
    # rebuild history per-call to filter out cross-conversation leak.
    scope_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    kind: Mapped[str | None]    = mapped_column(String(20), nullable=True)  # chat | run_step | …
    role: Mapped[MessageRole]   = mapped_column(SAEnum(MessageRole), nullable=False)
    content: Mapped[str]        = mapped_column(Text, default="")
    tool_name: Mapped[str | None]   = mapped_column(String(120), nullable=True)
    tool_input: Mapped[str | None]  = mapped_column(Text, nullable=True)
    tool_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int]   = mapped_column(Integer, default=0)
    output_tokens: Mapped[int]  = mapped_column(Integer, default=0)
    cost_usd: Mapped[float]     = mapped_column(Float, default=0.0)
    model_used: Mapped[str]     = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="messages")


# ── WebhookLog ──────────────────────────────────────────────────────────

class Conversation(Base):
    """Continuity handle for a multi-turn exchange between an agent and a
    runtime that supports resume.

    `scope_key` identifies WHICH conversation this is (see
    services.conversation_scope_key for the scheme: run:<id>,
    chat:project:<pid>, chat:default, future thread:<id> etc.). The
    (agent_id, scope_key) pair is unique — at most one active session
    handle per conversation. `runtime_session_id` is the runtime-native
    handle (claude session_id); empty/null for gateway runtimes that
    rebuild history per call.

    Chat dispatches do NOT create Runs. Conversation continuity lives
    here so chat triggers stay lightweight while still being resumable.
    """
    __tablename__ = "forge_conversations"
    __table_args__ = (UniqueConstraint("agent_id", "scope_key"),)

    id: Mapped[str]                = mapped_column(String(12), primary_key=True, default=_new_id)
    agent_id: Mapped[str]          = mapped_column(ForeignKey("forge_agents.id"), nullable=False)
    scope_key: Mapped[str]         = mapped_column(String(120), nullable=False)
    runtime_session_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Rolling compaction carry-over for context assembly. When the rebuilt
    # history exceeds the token budget, older turns are folded into this
    # summary instead of being silently dropped. `rolling_summary_through_run_id`
    # is the high-water mark — runs/turns after it aren't yet folded in.
    rolling_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    rolling_summary_through_run_id: Mapped[str | None] = mapped_column(
        String(12), nullable=True)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime]   = mapped_column(DateTime(timezone=True), default=_utcnow)


class QueuedMessage(Base):
    """A user message sent while a turn was already running in this scope.

    A conversation is single-threaded (one live turn at a time), so a message
    typed mid-run is queued here instead of interrupting — it dispatches FIFO
    when the active turn reaches a terminal state. Keyed by (agent_id,
    scope_key) = the conversation, NOT the active run: a queued message must
    survive even if that run is discarded. Rows are deleted as they dispatch.
    (Replaces the old Run.pending_steer parking, which interrupted the run.)
    """
    __tablename__ = "forge_queued_messages"

    id: Mapped[str]             = mapped_column(String(12), primary_key=True, default=_new_id)
    agent_id: Mapped[str]       = mapped_column(ForeignKey("forge_agents.id"), nullable=False)
    scope_key: Mapped[str]      = mapped_column(String(120), nullable=False, index=True)
    content: Mapped[str]        = mapped_column(Text, default="")
    user_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WebhookLog(Base):
    """Log entry for inbound/outbound webhook calls."""
    __tablename__ = "forge_webhook_logs"

    id: Mapped[str]             = mapped_column(String(12), primary_key=True, default=_new_id)
    agent_id: Mapped[str]       = mapped_column(ForeignKey("forge_agents.id"), nullable=False)
    direction: Mapped[str]      = mapped_column(String(10), default="outbound")
    url: Mapped[str]            = mapped_column(String(500), default="")
    event: Mapped[str]          = mapped_column(String(60), default="")
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool]       = mapped_column(default=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DispatchIntent(Base):
    """Durable outbox row for a daemon-bound WS frame (AP-390).

    Written by WsHub.dispatch_* before any send attempt so a dispatch
    triggered in a process that doesn't hold the daemon's WS socket
    (flowty-mcp serving finish_run, a redeploy window, a second replica)
    survives until the flowty-api delivery loop — or the daemon's next
    WS registration — sends it through a live connection. The payload is
    the complete ready-to-send frame; delivery is at-least-once (the
    daemon dedups by event_id and its inflight registry keys by scope).
    """
    __tablename__ = "forge_dispatch_intents"

    id: Mapped[str]             = mapped_column(String(12), primary_key=True, default=_new_id)
    kind: Mapped[str]           = mapped_column(String(20), default="trigger")  # trigger|integrate|cancel
    event_id: Mapped[str]       = mapped_column(String(80), default="", index=True)
    runtime_id: Mapped[str]     = mapped_column(String(40), default="", index=True)
    agent_id: Mapped[str]       = mapped_column(String(40), default="")
    run_id: Mapped[str]         = mapped_column(String(40), default="")
    task_id: Mapped[str]        = mapped_column(String(40), default="")
    payload_json: Mapped[str]   = mapped_column(Text, default="{}")
    status: Mapped[str]         = mapped_column(String(12), default="pending", index=True)  # pending|delivered|failed
    attempts: Mapped[int]       = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlanningTurn(Base):
    """A durable, auditable record of one Conductor planning turn (AP-401).

    Today a planning turn's reasoning lived only in server logs — this row
    is the transparent record: what the Conductor saw (facts_snapshot) and
    what it decided (decisions), so the loop can be audited from the board
    instead of SSH-ing into logs. `decisions` is appended to as individual
    decisions land (see `planning_turns.append_decision`) — a turn that
    dispatches async (LLM tool calls arrive later) starts with an empty
    list and fills in over time; a turn that skips synchronously (nothing
    to plan) is recorded complete immediately.
    """
    __tablename__ = "forge_planning_turns"

    id: Mapped[str]             = mapped_column(String(12), primary_key=True, default=_new_id)
    trigger: Mapped[str]        = mapped_column(String(20), default="cron")  # "cron" | "event"
    status: Mapped[str]         = mapped_column(String(20), default="dispatched")  # dispatched|skipped|error
    model: Mapped[str | None]   = mapped_column(String(120), nullable=True)
    token_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int | None]  = mapped_column(Integer, nullable=True)
    # JSON blob: {agents: [...], unassigned_tasks: [...]} — the facts the
    # Conductor reasoned over. Lean by construction (gather_planning_facts
    # already caps rows/description length) — never a full transcript.
    facts_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON list of {action, task_id, agent, reason} — one per decision.
    decisions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where the full transcript lives — the Conductor's own conversation.
    conversation_scope_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
