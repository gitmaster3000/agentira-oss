"""Forge domain models — Agents and Runs."""

import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String, Text, Integer, Float, DateTime,
    ForeignKey, Enum as SAEnum,
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
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


# ── Agent ────────────────────────────────────────────────────────────────

class Agent(Base):
    """A runtime executor — an agent instance that picks up and runs work."""
    __tablename__ = "forge_agents"

    id: Mapped[str]             = mapped_column(String(12), primary_key=True, default=_new_id)
    profile_id: Mapped[str]     = mapped_column(ForeignKey("profiles.id"), nullable=False)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    profile = relationship("Profile")
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
