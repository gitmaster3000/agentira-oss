"""SQLAlchemy ORM models for AgentIRA."""

import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, Enum as SAEnum, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Enums ────────────────────────────────────────────────────────────────

class TaskPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationTransport(str, enum.Enum):
    WEBHOOK = "webhook"
    SSE     = "sse"    # Phase 2 — column exists, dispatch logic ships later
    POLL    = "poll"


# ── Auth ─────────────────────────────────────────────────────────────────

class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)

    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role", cascade="all, delete-orphan")
    profiles: Mapped[list["Profile"]] = relationship(back_populates="role")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    codename: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class RolePermission(Base):
    """Which permissions a role grants."""
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), nullable=False)
    permission_id: Mapped[str] = mapped_column(ForeignKey("permissions.id"), nullable=False)

    role: Mapped["Role"] = relationship(back_populates="permissions")
    permission: Mapped["Permission"] = relationship()


class ProfilePermission(Base):
    """Extra permissions granted directly to a profile (beyond their role)."""
    __tablename__ = "profile_permissions"
    __table_args__ = (UniqueConstraint("profile_id", "permission_id"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False)
    permission_id: Mapped[str] = mapped_column(ForeignKey("permissions.id"), nullable=False)

    profile: Mapped["Profile"] = relationship(back_populates="extra_permissions")
    permission: Mapped["Permission"] = relationship()


class Status(Base):
    __tablename__ = "statuses"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


# ── Core ─────────────────────────────────────────────────────────────────

class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(128), default="")  # Simple hash (e.g. sha256)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, default=None)
    avatar_url: Mapped[str] = mapped_column(String(500), default="")
    api_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, default=None)
    webhook_url: Mapped[str] = mapped_column(String(500), default="")
    notification_transport: Mapped[str | None] = mapped_column(
        SAEnum(NotificationTransport), nullable=True, default=None
    )
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # ── Runtime config (agents only; humans leave these null) ────────────
    # AP-86: bot ↔ agent merge. Bot profiles ARE agents. These columns used
    # to live on forge_agents — folded onto Profile so there's one identity
    # row per AI worker. forge_agents stays as a transitional FK target
    # until callers migrate; new writes go here.
    model: Mapped[str] = mapped_column(String(120), default="")
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    personality: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    runtime_id: Mapped[str | None] = mapped_column(
        ForeignKey("forge_runtimes.id"), nullable=True, default=None
    )
    default_project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True, default=None
    )
    # Filesystem path of the agent's home directory. The agent's repos,
    # memory, and scratch live here. Daemon defaults cwd to this path
    # (general chats) or to <home>/repos/<project>/ (project chats).
    # NULL → derive default `~/.agentira/agents/<id>/home/` at dispatch.
    home_path: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    mcp_servers: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Names of built-in servers (agentira, memory) the user has explicitly
    # disabled for this agent. JSON list of strings. Applied AFTER the
    # registry merge so it can strip auto-injected servers too.
    mcp_disabled: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Strict MCP mode: when true, daemon passes --strict-mcp-config (claude)
    # so the agent ONLY sees Agentira-managed servers — user's host MCP
    # (~/.claude.json) is ignored. Default false = merge host + ours.
    mcp_strict: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Free-form MCP config override. Stores a raw JSON object of shape
    # {"mcpServers": {name: {...definition...}}}. Whatever's here is
    # merged INTO the resolved config from the registry, AFTER auto +
    # opt-in servers. Last-write-wins on name collisions, so a key here
    # named "agentira" or "memory" replaces the auto-injected one.
    # Lets users add custom servers without modifying mcp_registry.py.
    mcp_config_override: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # User-provided secrets injected into the dispatched runtime's env
    # (GH_TOKEN, OPENAI_API_KEY, etc.). JSON object {KEY: VALUE}.
    env_vars: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # AP-80 Conductor: opt-in autonomous task pickup. When true, the
    # Conductor loop dispatches the next eligible todo task to this agent
    # whenever the agent is idle. Default OFF — surprise autonomy is bad.
    conductor_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    max_concurrent_runs: Mapped[int] = mapped_column(default=1, nullable=False)
    # System-provided agents (the Conductor, the Concierge) — seeded by
    # Agentira, not user-created. Protected from deletion. Default False.
    is_system: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Conductor cadence config — only meaningful on the Conductor's own
    # profile. conductor_tick_seconds: queue-tick interval; report_time:
    # daily-report time "HH:MM" (UTC). conductor_report_enabled gates the
    # daily report independently of the queue tick.
    conductor_tick_seconds: Mapped[int] = mapped_column(default=60, nullable=False)
    conductor_report_time: Mapped[str] = mapped_column(String(5), default="09:00", nullable=False)
    conductor_report_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    # How often (minutes) the Conductor takes an LLM planning turn —
    # assigning unassigned todo tasks to the best-fit agent.
    conductor_plan_interval_minutes: Mapped[int] = mapped_column(default=10, nullable=False)
    # Master on/off for the Conductor (on its own profile). When False the
    # queue tick, planning turn, and daily report all no-op.
    conductor_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    role: Mapped["Role"] = relationship(back_populates="profiles")
    extra_permissions: Mapped[list["ProfilePermission"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    project_memberships: Mapped[list["ProjectMember"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(back_populates="profile", cascade="all, delete-orphan")


class OAuthAccount(Base):
    """Links an external OAuth provider (google, github, etc.) to a Profile."""
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)        # "google", "github"
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)  # sub / github user id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    profile: Mapped["Profile"] = relationship(back_populates="oauth_accounts")


class ProjectMember(Base):
    """Link table: Profile <-> Project."""
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "profile_id"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False)

    project: Mapped["Project"] = relationship(back_populates="members")
    profile: Mapped["Profile"] = relationship(back_populates="project_memberships")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # project.member.add, task.assign
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    link: Mapped[str] = mapped_column(String(255), default="")      # e.g. /projects/123
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    profile: Mapped["Profile"] = relationship(back_populates="notifications")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    key_prefix: Mapped[str] = mapped_column(String(10), nullable=False, default="PROJ")
    next_task_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    webhook_config: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Run context — used when an agent is dispatched against a task in this project.
    # repo_path: local filesystem path the daemon worktrees off (same-machine default).
    # repo_url: optional git remote URL — daemon clones from here when repo_path
    #   isn't accessible (cloud / different machine).
    # conventions_md: runtime-agnostic markdown materialized to .agentira/CONVENTIONS.md.
    repo_path: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    conventions_md: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    epics: Mapped[list["Epic"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    activities: Mapped[list["Activity"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Activity.created_at.desc()")


class Epic(Base):
    __tablename__ = "epics"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="backlog")  # backlog | in_progress | done
    assignee: Mapped[str] = mapped_column(String(120), default="")
    creator: Mapped[str] = mapped_column(String(120), default="")
    color: Mapped[str] = mapped_column(String(7), default="#7c4dff")  # hex color
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    project: Mapped["Project"] = relationship(back_populates="epics")
    tasks: Mapped[list["Task"]] = relationship(back_populates="epic", foreign_keys="Task.epic_id")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    key: Mapped[str] = mapped_column(String(20), nullable=True, unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    epic_id: Mapped[str | None] = mapped_column(ForeignKey("epics.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status_id: Mapped[str] = mapped_column(ForeignKey("statuses.id"), nullable=False)
    priority: Mapped[TaskPriority] = mapped_column(SAEnum(TaskPriority), default=TaskPriority.MEDIUM)
    assignee: Mapped[str] = mapped_column(String(120), default="")
    creator: Mapped[str] = mapped_column(String(120), default="")
    tags: Mapped[str] = mapped_column(String(500), default="")
    dod_items: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: [{"text": "...", "checked": false}]
    branch: Mapped[str] = mapped_column(String(255), default="")
    pr_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    project: Mapped["Project"] = relationship(back_populates="tasks")
    epic: Mapped["Epic | None"] = relationship(back_populates="tasks", foreign_keys=[epic_id])
    status: Mapped["Status"] = relationship()
    activities: Mapped[list["Activity"]] = relationship(back_populates="task", cascade="all, delete-orphan",
                                                         order_by="Activity.created_at.desc()")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    commits: Mapped[list["TaskCommit"]] = relationship(back_populates="task", cascade="all, delete-orphan",
                                                        order_by="TaskCommit.committed_at.desc()")


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    
    actor: Mapped[str] = mapped_column(String(120), default="system")
    action: Mapped[str] = mapped_column(String(60), nullable=False)  # e.g. project.create, task.assign
    detail: Mapped[str] = mapped_column(Text, default="")
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON: {"field": {"from": x, "to": y}}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    project: Mapped["Project"] = relationship(back_populates="activities")
    task: Mapped["Task"] = relationship(back_populates="activities")


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(default=0)
    uploaded_by: Mapped[str] = mapped_column(String(120), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    task: Mapped["Task"] = relationship(back_populates="attachments")


# ── Git Integration ─────────────────────────────────────────────────────

class TaskCommit(Base):
    """A git commit or PR linked to a task."""
    __tablename__ = "task_commits"

    id: Mapped[str]          = mapped_column(String(12), primary_key=True, default=_new_id)
    task_id: Mapped[str]     = mapped_column(ForeignKey("tasks.id"), nullable=False)
    sha: Mapped[str]         = mapped_column(String(40), nullable=False)
    message: Mapped[str]     = mapped_column(Text, default="")
    author: Mapped[str]      = mapped_column(String(120), default="")
    branch: Mapped[str]      = mapped_column(String(255), default="")
    url: Mapped[str]         = mapped_column(String(500), default="")
    repo: Mapped[str]        = mapped_column(String(255), default="")
    kind: Mapped[str]        = mapped_column(String(20), default="commit")  # commit | pr
    pr_state: Mapped[str]    = mapped_column(String(20), default="")       # open | closed | merged (for PRs)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    task: Mapped["Task"] = relationship(back_populates="commits")
