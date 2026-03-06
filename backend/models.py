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
    avatar_url: Mapped[str] = mapped_column(String(500), default="")
    api_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, default=None)
    webhook_url: Mapped[str] = mapped_column(String(500), default="")
    notification_transport: Mapped[str | None] = mapped_column(
        SAEnum(NotificationTransport), nullable=True, default=None
    )
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    role: Mapped["Role"] = relationship(back_populates="profiles")
    extra_permissions: Mapped[list["ProfilePermission"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    project_memberships: Mapped[list["ProjectMember"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="profile", cascade="all, delete-orphan")


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
    webhook_config: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    activities: Mapped[list["Activity"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Activity.created_at.desc()")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status_id: Mapped[str] = mapped_column(ForeignKey("statuses.id"), nullable=False)
    priority: Mapped[TaskPriority] = mapped_column(SAEnum(TaskPriority), default=TaskPriority.MEDIUM)
    assignee: Mapped[str] = mapped_column(String(120), default="")
    tags: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    project: Mapped["Project"] = relationship(back_populates="tasks")
    status: Mapped["Status"] = relationship()
    activities: Mapped[list["Activity"]] = relationship(back_populates="task", cascade="all, delete-orphan",
                                                         order_by="Activity.created_at.desc()")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="task", cascade="all, delete-orphan")


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
