"""SQLAlchemy ORM models for AgentIRA."""

import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, Enum as SAEnum, UniqueConstraint, Table, Column
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

# Account type (what an identity IS) — orthogonal to roles (what it MAY do).
#   human          — a person; logs in with email + password.
#   agentira_agent — an AI agent dispatched/managed inside Agentira.
#   external_agent — a service account; external systems auth with an API key.
ACCOUNT_TYPES = ("human", "agentira_agent", "external_agent")


# Many-to-many: a profile holds one or more roles (permission tiers). Pure
# association, no extra columns — a plain Table, not a mapped class.
profile_roles = Table(
    "profile_roles",
    Base.metadata,
    Column("profile_id", ForeignKey("profiles.id"), primary_key=True),
    Column("role_id", ForeignKey("roles.id"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)

    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role", cascade="all, delete-orphan")
    profiles: Mapped[list["Profile"]] = relationship(secondary=profile_roles, back_populates="roles")


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
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False)
    permission_id: Mapped[str] = mapped_column(ForeignKey("permissions.id"), nullable=False)

    profile: Mapped["Profile"] = relationship(back_populates="extra_permissions")
    permission: Mapped["Permission"] = relationship()


class Status(Base):
    __tablename__ = "statuses"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


# ── Tenancy ──────────────────────────────────────────────────────────────
# An Org is the multi-tenancy boundary. Every signup creates a new org and
# the new profile becomes its admin. All scoped tables carry org_id; Postgres
# RLS policies (configured in scripts/apply_rls.py) enforce isolation even
# when application code forgets a WHERE clause.

class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Per-org caps (tunable later). Members = non-bot profiles beyond the
    # founding admin; agents = bot profiles.
    max_members: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    max_agents: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Invite(Base):
    """Invite code for invite-only signup.

    - Admin invite: org_id NULL, role='admin' → accepting creates a NEW org
      and the invitee becomes its admin (operator-issued).
    - Member invite: org_id set, role='member' → accepting creates a profile
      in that org (admin-issued, capped by Org.max_members).

    NOT org-scoped: an admin invite has no org yet, and accept happens before
    the invitee has an org context. Lookups are by unguessable `code`.
    """
    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("orgs.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invited_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_profile_id: Mapped[str | None] = mapped_column(String(12), nullable=True)


# ── Core ─────────────────────────────────────────────────────────────────

class Profile(Base):
    __tablename__ = "profiles"
    # Name is unique PER ORG (not globally) so every org can have its own
    # "Conductor", "Planner", etc. Human usernames are additionally kept
    # globally unique in app code (signup/accept) so password login by username
    # stays unambiguous.
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_profiles_org_name"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(128), default="")  # Simple hash (e.g. sha256)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, default=None)
    # AP-306: password lifecycle. must_change_password is set when an admin
    # sets/resets a password (or for any temp credential) so the UI forces a
    # change on next login. reset_token + expiry back the forgot-password flow.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reset_token: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    reset_token_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    avatar_url: Mapped[str] = mapped_column(String(500), default="")
    api_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, default=None)
    webhook_url: Mapped[str] = mapped_column(String(500), default="")
    notification_transport: Mapped[str | None] = mapped_column(
        SAEnum(NotificationTransport), nullable=True, default=None
    )
    # What this identity IS (human / agentira_agent / external_agent). Stored,
    # not derived — decoupled from roles. See ACCOUNT_TYPES.
    account_type: Mapped[str] = mapped_column(String(20), default="human", nullable=False)
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
    # AP-302: personal git access token (PAT) for this agent/user. Used at
    # dispatch as a fallback when the target project_repo has no token of its
    # own. validity is cached the same way as project_repos. Never serialized.
    git_token: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    git_token_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    git_token_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None)

    roles: Mapped[list["Role"]] = relationship(secondary=profile_roles, back_populates="profiles")
    extra_permissions: Mapped[list["ProfilePermission"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    project_memberships: Mapped[list["ProjectMember"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(back_populates="profile", cascade="all, delete-orphan")

    @property
    def role_names(self) -> list[str]:
        return [r.name for r in self.roles]


class OAuthAccount(Base):
    """Links an external OAuth provider (google, github, etc.) to a Profile."""
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
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
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False)

    project: Mapped["Project"] = relationship(back_populates="members")
    profile: Mapped["Profile"] = relationship(back_populates="project_memberships")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
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
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
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
    # AP-308: per-run environment isolation. The worktree forks the *source*;
    # this forks the *runtime environment* a run's commands hit so concurrent
    # runs can't collide on the shared dev stack (the org_id/port/migration
    # race class). NULL/"auto" → resolved at dispatch (per_run_db when a DB
    # service is present, else hermetic). "hermetic" | "per_run_db" |
    # "per_run_compose". The override cmds/admin URL are NULL unless a project
    # needs a custom setup; built-in defaults live daemon-side.
    env_isolation: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    env_setup_cmd: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    env_teardown_cmd: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    env_db_admin_url: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
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
    # AP-297: how long a run's cached pre-checks stay trusted before they're
    # re-validated on the next on-ready fetch. NULL = default (600s / 10 min);
    # 0 = never expire by age (only an operational-env change re-runs them).
    ready_checks_ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
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
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)  # e.g. "backend", "frontend"
    repo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(120), default="main")
    # AP-296: how fresh an agent's work desk starts. always_latest (default) =
    # cut/rebase off the latest default_branch; new_only = latest for new desks
    # but never rebase resumed work; pinned = opt-in, frozen base (loud warning).
    worktree_freshness: Mapped[str] = mapped_column(String(20), default="always_latest")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    # AP-302: git access token (PAT) so agents dispatched against this repo
    # can clone/push private repos. token_valid/token_checked_at cache the
    # last validity probe (None = never checked). The token value is never
    # returned by the API — only has_token + validity.
    access_token: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    token_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    token_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Epic(Base):
    __tablename__ = "epics"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
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
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="epic", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_tasks_project_key"),)

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(20), nullable=True)
    # Task type discriminator — a task can be a plain task, a bug, etc.
    # Type-specific behavior lives in backend.tasks.TaskService subclasses.
    type: Mapped[str] = mapped_column(String(20), default="task", nullable=False)
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
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
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
    org_id: Mapped[str] = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
    # AP-152/AP-351: a row attaches to exactly one of task_id, project_id or
    # epic_id. All three are nullable at the DB level; the one-of invariant is
    # enforced in `backend.attachments.add`.
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    epic_id: Mapped[str | None] = mapped_column(ForeignKey("epics.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(default=0)
    uploaded_by: Mapped[str] = mapped_column(String(120), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    task: Mapped["Task | None"] = relationship(back_populates="attachments")
    project: Mapped["Project | None"] = relationship(back_populates="attachments")
    epic: Mapped["Epic | None"] = relationship(back_populates="attachments")


# ── Git Integration ─────────────────────────────────────────────────────

class TaskCommit(Base):
    """A git commit or PR linked to a task."""
    __tablename__ = "task_commits"

    id: Mapped[str]          = mapped_column(String(12), primary_key=True, default=_new_id)
    org_id: Mapped[str]      = mapped_column(ForeignKey("orgs.id"), nullable=False, index=True)
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
