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
    # AP-155: agent-level containment policy for dispatched runs. NULL =
    # workspace default ("off"). Project-level override wins if set; see
    # backend.sandbox.resolve_mode. Values: off | cwd | strict | container.
    sandbox_mode: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)

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
    # AP-197: how the daemon provisions this project's working copy.
    #   "git"          — clone repo_url into ~/.agentira/sources and worktree
    #                    off that clone (daemon owns the copy; never touches the
    #                    user's protected folders like ~/Desktop).
    #   "sandbox"      — no repo; a plain working dir, deliverables = artifacts.
    #   "local_folder" — use repo_path on the host as-is (power-user; deferred).
    # NULL → inferred (repo_url → git, repo_path-only → local_folder, else sandbox).
    workspace_kind: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    conventions_md: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # AP-4: provenance + registry for projects spawned from a template.
    # template_name is the source template's `name` field — also drives
    # idempotency in `instantiate_project_from_template`.
    # ac_check_types_json is the JSON list of AC check definitions the
    # template registered (used later by the gate engine).
    template_name: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    ac_check_types_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # CLEANUP(AP-190): remove. No crystallization → no work-signal mode. The
    # daemon's git facts become observed run metadata, not a per-turn gate.
    # ADR 009 / AP-136: work-signal mode deciding when a standalone chat turn
    # crystallizes into a run — "working_tree" (default; any tracked change or
    # new untracked file), "tracked", or "committed". NULL = workspace default.
    work_signal: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    # AP-155: project-level containment override. NULL = inherit from the
    # agent (Profile.sandbox_mode); both NULL = workspace default ("off").
    sandbox_mode: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    # AP-158: column-exit gate enforcement on transitions. False/NULL =
    # off (today's behavior — move_task only RBAC-checks). True = the
    # gate engine evaluates the transition; any failed gate blocks it
    # with structured reasons. Defaults to False so existing projects
    # keep working unchanged.
    gates_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # AP-184: when True, ANY comment on a task wakes the assigned agent (the
    # legacy behavior). Default False — a plain comment is recorded into the
    # task chat as context and the agent reads it when it next starts work; only
    # a comment that @mentions the agent wakes it immediately. Avoids the
    # surprise of every comment auto-starting a run.
    wake_on_comment: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Workflow driver (backend/forge/workflow.py): when True, a successful run
    # advances the task per the system flow (templates/workflow/default.yaml)
    # — e.g. in_progress -> review with a reviewer (!= implementer) dispatched.
    # Default False: nothing changes for projects that don't opt in.
    workflow_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # The ONLY customer-editable workflow surface: a JSON object overriding
    # how roles resolve to agents ({"reviewer": {"match": [...], ...}}).
    # Validated (Pydantic RoleSpec) on use; the flow itself is system config.
    workflow_roles_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    epics: Mapped[list["Epic"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    activities: Mapped[list["Activity"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Activity.created_at.desc()")
    # AP-152: project-level attachments (briefs, designs, brand guides).
    # Same Attachment table — row carries project_id XOR task_id.
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        primaryjoin="Project.id == Attachment.project_id",
    )


class ProjectRepo(Base):
    """AP-121: a project can map to multiple git repos.

    The legacy `Project.repo_path` / `Project.repo_url` model assumed one
    project = one repo. Real codebases (UI + backend + MCP) often span
    repos. Each task picks a target repo via `Task.repo_name`; the
    primary repo is the default when a task doesn't specify.
    """
    __tablename__ = "project_repos"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)  # e.g. "backend", "frontend"
    repo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(120), default="main")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


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
    # AP-121: which repo in the project this task targets. NULL = the
    # project's primary repo (back-compat with single-repo projects).
    # Validated at create/update time against project_repos.name.
    repo_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # AP-154: multiple repos a task touches (JSON list of project_repos.name).
    # NULL = derive from repo_name (legacy) or the project's primary repo.
    # The daemon materializes each as a named subdirectory of the agent
    # workdir, so the agent has every linked repo inside its sandbox.
    repos_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
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
    # AP-152: task_id XOR project_id — a row attaches to exactly one of them.
    # Both columns are nullable at the DB level; the XOR invariant is
    # enforced in `backend.attachments.add`.
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(default=0)
    uploaded_by: Mapped[str] = mapped_column(String(120), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    task: Mapped["Task | None"] = relationship(back_populates="attachments")
    project: Mapped["Project | None"] = relationship(back_populates="attachments")


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
