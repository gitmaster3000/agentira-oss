"""FastAPI REST API — thin wrapper around the facade service."""

from __future__ import annotations
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend import services

# ── Pydantic schemas ─────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    actor: str = "system"

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class TaskCreate(BaseModel):
    project_id: str
    title: str
    description: str = ""
    status: str = "backlog"
    priority: str = "medium"
    assignee: str = ""
    tags: list[str] = Field(default_factory=list)
    actor: str = "system"

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    tags: Optional[list[str]] = None
    actor: str = "system"

class TaskMove(BaseModel):
    status: str
    actor: str = "system"

class CommentCreate(BaseModel):
    comment: str
    actor: str = "system"

class ProfileCreate(BaseModel):
    name: str
    display_name: str = ""
    role: str = "member"
    avatar_url: str = ""

class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    avatar_url: Optional[str] = None

class ProfileSignup(BaseModel):
    name: str
    display_name: str = ""
    password: str

class ServiceAccountCreate(BaseModel):
    name: str

# ── App ──────────────────────────────────────────────────────────────────

app = FastAPI(title="AgentIRA", version="0.1.0", description="Lean task manager for AI agents")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoginRequest(BaseModel):
    username: str
    password: str

@app.on_event("startup")
def startup():
    # services.bootstrap() removed - run scripts/bootstrap_db.py manually
    pass


# ── Auth ─────────────────────────────────────────────────────────────────

@app.post("/api/login")
def api_login(body: LoginRequest):
    user = services.authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    return {"user": user}


@app.post("/api/signup")
def api_signup(body: ProfileSignup):
    try:
        return services.signup(body.name, body.display_name, body.password)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/profiles/me")
def api_get_me(actor: str):
    """Identify user via simulated cookie (actor name) and return profile data.
    Note: For agents, this returns the API key so it can be managed in UI.
    """
    with services._session() as db:
        p = services._get_profile_by_name(db, actor)
        if not p:
            raise HTTPException(404, "Profile not found")
        res = services._profile_to_dict(p)
        res["api_key"] = p.api_key  # Include key for self-management
        return res


# ── Service Accounts ─────────────────────────────────────────────────────

@app.post("/api/service-accounts")
def api_create_service_account(body: ServiceAccountCreate, actor: str = "system"):
    """Create a new service account (bot) and return its API key."""
    # Check if actor is admin? For now, allow any member to create a bot (dev feature).
    # TODO: Enforce admin only if strict.
    try:
        return services.create_service_account(body.name)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/service-accounts")
def api_list_service_accounts():
    """List all service accounts."""
    return services.list_profiles(role="bot")


@app.get("/api/service-accounts/{profile_id}")
def api_get_service_account(profile_id: str):
    """Get service account details including API key."""
    result = services.get_service_account(profile_id)
    if not result:
        raise HTTPException(404, "Service account not found")
    return result


@app.delete("/api/service-accounts/{profile_id}")
def api_delete_service_account(profile_id: str):
    """Delete a service account."""
    if not services.delete_profile(profile_id):
        raise HTTPException(404, "Profile not found")
    return {"ok": True}


# ── Projects ─────────────────────────────────────────────────────────────

@app.post("/api/projects")
def api_create_project(body: ProjectCreate):
    return services.create_project(body.name, body.description, actor=body.actor)

@app.get("/api/projects")
def api_list_projects(actor: str = "system"):
    return services.list_projects(actor=actor)

@app.get("/api/projects/{project_id}")
def api_get_project(project_id: str):
    result = services.get_project(project_id)
    if not result:
        raise HTTPException(404, "Project not found")
    return result

@app.patch("/api/projects/{project_id}")
def api_update_project(project_id: str, body: ProjectUpdate):
    try:
        return services.update_project(project_id, name=body.name, description=body.description)
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: str):
    if not services.delete_project(project_id):
        raise HTTPException(404, "Project not found")
    return {"ok": True}


@app.post("/api/projects/{project_id}/members")
def api_add_project_member(project_id: str, body: dict):
    """Body: {"profile_name": "alice", "actor": "system"}"""
    try:
        actor = body.get("actor", "system")
        return services.add_project_member(project_id, body["profile_name"], actor=actor)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/projects/{project_id}/members")
def api_list_project_members(project_id: str):
    return services.list_project_members(project_id)


@app.delete("/api/projects/{project_id}/members/{profile_name}")
def api_remove_project_member(project_id: str, profile_name: str):
    if not services.remove_project_member(project_id, profile_name):
        raise HTTPException(404, "Member not found")
    return {"ok": True}


# ── Tasks ────────────────────────────────────────────────────────────────

@app.post("/api/tasks")
def api_create_task(body: TaskCreate):
    try:
        return services.create_task(
            project_id=body.project_id,
            title=body.title,
            description=body.description,
            status=body.status,
            priority=body.priority,
            assignee=body.assignee,
            tags=body.tags,
            actor=body.actor,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get("/api/tasks")
def api_list_tasks(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    priority: Optional[str] = None,
    actor: str = "system",
):
    return services.list_tasks(project_id=project_id, status=status, assignee=assignee, priority=priority, actor=actor)

@app.get("/api/tasks/{task_id}")
def api_get_task(task_id: str):
    result = services.get_task(task_id)
    if not result:
        raise HTTPException(404, "Task not found")
    return result

@app.patch("/api/tasks/{task_id}")
def api_update_task(task_id: str, body: TaskUpdate):
    try:
        return services.update_task(
            task_id=task_id,
            title=body.title,
            description=body.description,
            priority=body.priority,
            assignee=body.assignee,
            tags=body.tags,
            actor=body.actor,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.delete("/api/tasks/{task_id}")
def api_delete_task(task_id: str):
    if not services.delete_task(task_id):
        raise HTTPException(404, "Task not found")
    return {"ok": True}

@app.post("/api/tasks/{task_id}/move")
def api_move_task(task_id: str, body: TaskMove):
    try:
        return services.move_task(task_id, body.status, body.actor)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/tasks/{task_id}/comment")
def api_add_comment(task_id: str, body: CommentCreate):
    try:
        return services.add_comment(task_id, body.comment, body.actor)
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.get("/api/tasks/{task_id}/activity")
def api_get_activity(task_id: str):
    return services.get_activity(task_id)

@app.get("/api/tasks/{task_id}/changes")
def api_get_changes(task_id: str, since: str):
    """Get task changes since a given ISO timestamp."""
    try:
        return services.get_changes_since(task_id, since)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get("/api/workflow/rules")
def api_get_rules():
    """Return all roles and their permissions."""
    return {"roles": services.list_roles()}


@app.get("/api/statuses")
def api_list_statuses():
    return services.list_statuses()


@app.get("/api/roles")
def api_list_roles():
    return services.list_roles()


@app.get("/api/permissions")
def api_list_permissions():
    return services.list_permissions()


class PermissionCreate(BaseModel):
    codename: str
    description: str = None

class RoleCreate(BaseModel):
    name: str
    description: str = None
    permissions: list[str] = []

@app.post("/api/permissions")
def api_create_permission(body: PermissionCreate):
    try:
        return services.create_permission(body.codename, body.description)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/roles")
def api_create_role(body: RoleCreate):
    try:
        return services.create_role(body.name, body.description, body.permissions)
    except ValueError as e:
        raise HTTPException(400, str(e))


class RolePermissionUpdate(BaseModel):
    role_name: str
    codename: str


@app.post("/api/permissions/grant")
def api_grant_permission(body: RolePermissionUpdate):
    if not services.grant_role_permission(body.role_name, body.codename):
        raise HTTPException(400, "Failed to grant permission")
    return {"ok": True}


@app.post("/api/permissions/revoke")
def api_revoke_permission(body: RolePermissionUpdate):
    if not services.revoke_role_permission(body.role_name, body.codename):
        raise HTTPException(400, "Failed to revoke permission")
    return {"ok": True}


# ── Board ────────────────────────────────────────────────────────────────

@app.get("/api/board/{project_id}")
def api_get_board(project_id: str):
    try:
        return services.get_board(project_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ── Attachments ──────────────────────────────────────────────────────────

@app.post("/api/tasks/{task_id}/attachments")
async def api_upload_attachment(
    task_id: str,
    file: UploadFile = File(...),
    uploaded_by: str = Form("admin"),
):
    try:
        file_bytes = await file.read()
        return services.add_attachment(
            task_id=task_id,
            filename=file.filename,
            file_bytes=file_bytes,
            content_type=file.content_type or "application/octet-stream",
            uploaded_by=uploaded_by,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.get("/api/tasks/{task_id}/attachments")
def api_list_attachments(task_id: str):
    return services.list_attachments(task_id)

@app.get("/api/attachments/{attachment_id}/download")
def api_download_attachment(attachment_id: str):
    result = services.get_attachment(attachment_id)
    if not result:
        raise HTTPException(404, "Attachment not found")
    meta, file_path = result
    import os
    if not os.path.exists(file_path):
        raise HTTPException(404, "File not found on disk")
    return FileResponse(file_path, filename=meta["filename"], media_type=meta["content_type"])

@app.delete("/api/attachments/{attachment_id}")
def api_delete_attachment(attachment_id: str):
    if not services.delete_attachment(attachment_id):
        raise HTTPException(404, "Attachment not found")
    return {"ok": True}


# ── Notifications ─────────────────────────────────────────────────────────────

@app.get("/api/notifications")
def api_list_notifications(actor: str, unread_only: bool = True):
    """List notifications for the given actor (profile name)."""
    with services._session() as db:
        prof = services._get_profile_by_name(db, actor)
        if not prof:
            raise HTTPException(404, "Profile not found")
        return services.list_notifications(prof.id, unread_only=unread_only)

@app.patch("/api/notifications/{notification_id}/read")
def api_mark_notification_read(notification_id: str):
    if not services.mark_notification_read(notification_id):
        raise HTTPException(404, "Notification not found")
    return {"ok": True}


# ── Project Activity ──────────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/activity")
def api_get_project_activity(project_id: str, limit: int = 50):
    """Get recent activity across all tasks in a project."""
    return services.get_project_activity(project_id, limit=limit)


# ── Profiles ──────────────────────────────────────────────────────────────

@app.post("/api/profiles")
def api_create_profile(body: ProfileCreate):
    try:
        return services.create_profile(body.name, body.display_name, body.role, body.avatar_url)
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/api/profiles")
def api_list_profiles(role: Optional[str] = None):
    return services.list_profiles(role=role)

@app.get("/api/profiles/{profile_id}")
def api_get_profile(profile_id: str):
    result = services.get_profile(profile_id)
    if not result:
        raise HTTPException(404, "Profile not found")
    return result

@app.patch("/api/profiles/{profile_id}")
def api_update_profile(profile_id: str, body: ProfileUpdate):
    try:
        return services.update_profile(profile_id, display_name=body.display_name, role=body.role, avatar_url=body.avatar_url)
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.delete("/api/profiles/{profile_id}")
def api_delete_profile(profile_id: str):
    if not services.delete_profile(profile_id):
        raise HTTPException(404, "Profile not found")
    return {"ok": True}
