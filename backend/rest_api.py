"""FastAPI REST API — entity-level routers, thin wrapper around services."""

from __future__ import annotations
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend import services

# ── Schemas ──────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class ProfileSignup(BaseModel):
    name: str
    display_name: str = ""
    password: str

class ProfileCreate(BaseModel):
    name: str
    display_name: str = ""
    role: str = "member"
    avatar_url: str = ""

class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    avatar_url: Optional[str] = None
    webhook_url: Optional[str] = None

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
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    epic_id: Optional[str] = None
    actor: str = "system"

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    tags: Optional[list[str]] = None
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    dod_items: Optional[list[dict]] = None
    branch: Optional[str] = None
    pr_url: Optional[str] = None
    epic_id: Optional[str] = None
    actor: str = "system"

class TaskMove(BaseModel):
    status: str
    actor: str = "system"

class CommentCreate(BaseModel):
    comment: str
    actor: str = "system"

class CommitLink(BaseModel):
    sha: str
    message: str = ""
    author: str = ""
    branch: str = ""
    url: str = ""
    repo: str = ""
    committed_at: Optional[str] = None

class PRLink(BaseModel):
    pr_number: int
    title: str = ""
    author: str = ""
    branch: str = ""
    url: str = ""
    repo: str = ""
    state: str = "open"

class EpicCreate(BaseModel):
    title: str
    description: str = ""
    status: str = "backlog"
    color: str = "#7c4dff"
    actor: str = "system"

class EpicUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    actor: str = "system"

class WebhookRuleSchema(BaseModel):
    event: str
    receivers: str

class WebhookConfigUpdate(BaseModel):
    enabled: bool = True
    rules: list[WebhookRuleSchema] = Field(default_factory=list)
    token: str = ""


# ── Auth Router ──────────────────────────────────────────────────────────

auth = APIRouter(prefix="/api", tags=["auth"])

@auth.post("/login")
def api_login(body: LoginRequest):
    user = services.authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    return {"user": user}

@auth.post("/signup")
def api_signup(body: ProfileSignup):
    try:
        return services.signup(body.name, body.display_name, body.password)
    except Exception as e:
        raise HTTPException(400, str(e))


# ── Profiles Router (includes service accounts) ─────────────────────────

profiles = APIRouter(prefix="/api/profiles", tags=["profiles"])

@profiles.get("/me")
def api_get_me(actor: str):
    with services._session() as db:
        p = services._get_profile_by_name(db, actor)
        if not p:
            raise HTTPException(404, "Profile not found")
        res = services._profile_to_dict(p)
        res["api_key"] = p.api_key
        return res

@profiles.get("")
def api_list_profiles(role: Optional[str] = None):
    return services.list_profiles(role=role)

@profiles.post("")
def api_create_profile(body: ProfileCreate):
    try:
        return services.create_profile(body.name, body.display_name, body.role, body.avatar_url)
    except Exception as e:
        raise HTTPException(400, str(e))

@profiles.get("/{profile_id}")
def api_get_profile(profile_id: str):
    result = services.get_profile(profile_id)
    if not result:
        raise HTTPException(404, "Profile not found")
    return result

@profiles.patch("/{profile_id}")
def api_update_profile(profile_id: str, body: ProfileUpdate):
    try:
        return services.update_profile(profile_id, display_name=body.display_name, role=body.role, avatar_url=body.avatar_url, webhook_url=body.webhook_url)
    except ValueError as e:
        raise HTTPException(404, str(e))

@profiles.delete("/{profile_id}")
def api_delete_profile(profile_id: str):
    if not services.delete_profile(profile_id):
        raise HTTPException(404, "Profile not found")
    return {"ok": True}

# Service accounts = profiles with role=bot
svc_accounts = APIRouter(prefix="/api/service-accounts", tags=["profiles"])

@svc_accounts.get("")
def api_list_service_accounts():
    return services.list_profiles(role="bot")

@svc_accounts.post("")
def api_create_service_account(body: dict):
    try:
        return services.create_service_account(body["name"])
    except Exception as e:
        raise HTTPException(400, str(e))

@svc_accounts.get("/{profile_id}")
def api_get_service_account(profile_id: str):
    result = services.get_service_account(profile_id)
    if not result:
        raise HTTPException(404, "Service account not found")
    return result

@svc_accounts.delete("/{profile_id}")
def api_delete_service_account(profile_id: str):
    if not services.delete_profile(profile_id):
        raise HTTPException(404, "Profile not found")
    return {"ok": True}


# ── Projects Router (includes members, board, roadmap, activity, webhooks) ──

projects = APIRouter(prefix="/api/projects", tags=["projects"])

@projects.get("")
def api_list_projects(actor: str = "system"):
    return services.list_projects(actor=actor)

@projects.post("")
def api_create_project(body: ProjectCreate):
    return services.create_project(body.name, body.description, actor=body.actor)

@projects.get("/{project_id}")
def api_get_project(project_id: str):
    result = services.get_project(project_id)
    if not result:
        raise HTTPException(404, "Project not found")
    return result

@projects.patch("/{project_id}")
def api_update_project(project_id: str, body: ProjectUpdate):
    try:
        return services.update_project(project_id, name=body.name, description=body.description)
    except ValueError as e:
        raise HTTPException(404, str(e))

@projects.delete("/{project_id}")
def api_delete_project(project_id: str):
    if not services.delete_project(project_id):
        raise HTTPException(404, "Project not found")
    return {"ok": True}

@projects.get("/{project_id}/members")
def api_list_project_members(project_id: str):
    return services.list_project_members(project_id)

@projects.post("/{project_id}/members")
def api_add_project_member(project_id: str, body: dict):
    try:
        return services.add_project_member(project_id, body["profile_name"], actor=body.get("actor", "system"))
    except ValueError as e:
        raise HTTPException(404, str(e))

@projects.delete("/{project_id}/members/{profile_name}")
def api_remove_project_member(project_id: str, profile_name: str):
    if not services.remove_project_member(project_id, profile_name):
        raise HTTPException(404, "Member not found")
    return {"ok": True}

@projects.get("/{project_id}/board")
def api_get_board(project_id: str):
    try:
        return services.get_board(project_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

@projects.get("/{project_id}/epics")
def api_list_epics(project_id: str):
    return services.list_epics(project_id)

@projects.post("/{project_id}/epics")
def api_create_epic(project_id: str, body: EpicCreate):
    try:
        return services.create_epic(project_id, title=body.title, description=body.description, color=body.color, actor=body.actor)
    except ValueError as e:
        raise HTTPException(400, str(e))

@projects.get("/{project_id}/roadmap")
def api_get_roadmap(project_id: str, group_by: str = "epic"):
    try:
        return services.get_roadmap(project_id, group_by=group_by)
    except ValueError as e:
        raise HTTPException(404, str(e))

@projects.get("/{project_id}/activity")
def api_get_project_activity(project_id: str, limit: int = 50):
    return services.get_project_activity(project_id, limit=limit)

@projects.get("/{project_id}/webhook-config")
def api_get_webhook_config(project_id: str):
    result = services.get_webhook_config(project_id)
    if result is None:
        raise HTTPException(404, "Project not found")
    return result

@projects.put("/{project_id}/webhook-config")
def api_put_webhook_config(project_id: str, body: WebhookConfigUpdate):
    try:
        return services.set_webhook_config(
            project_id, enabled=body.enabled,
            rules=[{"event": r.event, "receivers": r.receivers} for r in body.rules],
            token=body.token,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


# ── Tasks Router (includes comments, activity, attachments, git) ────────

tasks = APIRouter(prefix="/api/tasks", tags=["tasks"])

@tasks.get("")
def api_list_tasks(
    project_id: Optional[str] = None, status: Optional[str] = None,
    assignee: Optional[str] = None, priority: Optional[str] = None,
    actor: str = "system",
):
    return services.list_tasks(project_id=project_id, status=status, assignee=assignee, priority=priority, actor=actor)

@tasks.post("")
def api_create_task(body: TaskCreate):
    try:
        return services.create_task(
            project_id=body.project_id, title=body.title, description=body.description,
            status=body.status, priority=body.priority, assignee=body.assignee,
            tags=body.tags, start_date=body.start_date, due_date=body.due_date, 
            epic_id=body.epic_id, actor=body.actor,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

@tasks.get("/{task_id}")
def api_get_task(task_id: str):
    result = services.get_task(task_id)
    if not result:
        raise HTTPException(404, "Task not found")
    return result

@tasks.patch("/{task_id}")
def api_update_task(task_id: str, body: TaskUpdate):
    try:
        return services.update_task(
            task_id=task_id, title=body.title, description=body.description,
            priority=body.priority, assignee=body.assignee, tags=body.tags,
            start_date=body.start_date, due_date=body.due_date,
            dod_items=body.dod_items, branch=body.branch, pr_url=body.pr_url, 
            epic_id=body.epic_id, actor=body.actor,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

@tasks.delete("/{task_id}")
def api_delete_task(task_id: str):
    if not services.delete_task(task_id):
        raise HTTPException(404, "Task not found")
    return {"ok": True}

@tasks.post("/{task_id}/move")
def api_move_task(task_id: str, body: TaskMove):
    try:
        return services.move_task(task_id, body.status, body.actor)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

@tasks.post("/{task_id}/comment")
def api_add_comment(task_id: str, body: CommentCreate):
    try:
        return services.add_comment(task_id, body.comment, body.actor)
    except ValueError as e:
        raise HTTPException(404, str(e))

@tasks.get("/{task_id}/activity")
def api_get_activity(task_id: str):
    return services.get_activity(task_id)

@tasks.get("/{task_id}/changes")
def api_get_changes(task_id: str, since: str):
    try:
        return services.get_changes_since(task_id, since)
    except ValueError as e:
        raise HTTPException(400, str(e))

@tasks.get("/{task_id}/attachments")
def api_list_attachments(task_id: str):
    return services.list_attachments(task_id)

@tasks.post("/{task_id}/attachments")
async def api_upload_attachment(task_id: str, file: UploadFile = File(...), uploaded_by: str = Form("system")):
    try:
        file_bytes = await file.read()
        return services.add_attachment(task_id=task_id, filename=file.filename, file_bytes=file_bytes,
                                       content_type=file.content_type or "application/octet-stream", uploaded_by=uploaded_by)
    except ValueError as e:
        raise HTTPException(404, str(e))

@tasks.get("/{task_id}/commits")
def api_list_task_commits(task_id: str):
    return services.list_task_commits(task_id)

@tasks.post("/{task_id}/commits")
def api_link_commit(task_id: str, body: CommitLink):
    try:
        return services.link_commit(task_id, sha=body.sha, message=body.message, author=body.author,
                                     branch=body.branch, url=body.url, repo=body.repo, committed_at=body.committed_at)
    except ValueError as e:
        raise HTTPException(404, str(e))

@tasks.post("/{task_id}/prs")
def api_link_pr(task_id: str, body: PRLink):
    try:
        return services.link_pr(task_id, pr_number=body.pr_number, title=body.title, author=body.author,
                                 branch=body.branch, url=body.url, repo=body.repo, state=body.state)
    except ValueError as e:
        raise HTTPException(404, str(e))

@tasks.get("/{task_id}/suggest-branch")
def api_suggest_branch(task_id: str):
    result = services.suggest_branch_name(task_id)
    if not result:
        raise HTTPException(404, "Task not found")
    return result


# ── Attachments (standalone for download/delete by attachment ID) ────────

attachments = APIRouter(prefix="/api/attachments", tags=["tasks"])

@attachments.get("/{attachment_id}/download")
def api_download_attachment(attachment_id: str):
    result = services.get_attachment(attachment_id)
    if not result:
        raise HTTPException(404, "Attachment not found")
    meta, file_path = result
    import os
    if not os.path.exists(file_path):
        raise HTTPException(404, "File not found on disk")
    return FileResponse(file_path, filename=meta["filename"], media_type=meta["content_type"])

@attachments.delete("/{attachment_id}")
def api_delete_attachment(attachment_id: str):
    if not services.delete_attachment(attachment_id):
        raise HTTPException(404, "Attachment not found")
    return {"ok": True}


# ── Epics Router ─────────────────────────────────────────────────────────

epics_router = APIRouter(prefix="/api/epics", tags=["epics"])

# Moved below to app directly for reliability


@epics_router.patch("/{epic_id}")
def api_update_epic(epic_id: str, body: EpicUpdate):
    try:
        return services.update_epic(epic_id, title=body.title, description=body.description, color=body.color, actor=body.actor)
    except ValueError as e:
        raise HTTPException(404, str(e))

@epics_router.delete("/{epic_id}")
def api_delete_epic(epic_id: str):
    if not services.delete_epic(epic_id):
        raise HTTPException(404, "Epic not found")
    return {"ok": True}


# ── Workflow Router (statuses, roles, permissions) ───────────────────────

workflow = APIRouter(prefix="/api", tags=["workflow"])

@workflow.get("/statuses")
def api_list_statuses():
    return services.list_statuses()

@workflow.get("/roles")
def api_list_roles():
    return services.list_roles()

@workflow.get("/workflow/rules")
def api_get_rules():
    return {"roles": services.list_roles()}

@workflow.get("/permissions")
def api_list_permissions():
    return services.list_permissions()

@workflow.post("/permissions")
def api_create_permission(body: dict):
    try:
        return services.create_permission(body["codename"], body.get("description"))
    except ValueError as e:
        raise HTTPException(400, str(e))

@workflow.post("/roles")
def api_create_role(body: dict):
    try:
        return services.create_role(body["name"], body.get("description"), body.get("permissions", []))
    except ValueError as e:
        raise HTTPException(400, str(e))

@workflow.post("/permissions/grant")
def api_grant_permission(body: dict):
    if not services.grant_role_permission(body["role_name"], body["codename"]):
        raise HTTPException(400, "Failed to grant permission")
    return {"ok": True}

@workflow.post("/permissions/revoke")
def api_revoke_permission(body: dict):
    if not services.revoke_role_permission(body["role_name"], body["codename"]):
        raise HTTPException(400, "Failed to revoke permission")
    return {"ok": True}


# ── Notifications Router ─────────────────────────────────────────────────

notifications = APIRouter(prefix="/api/notifications", tags=["notifications"])

@notifications.get("")
def api_list_notifications(actor: str, unread_only: bool = True):
    with services._session() as db:
        prof = services._get_profile_by_name(db, actor)
        if not prof:
            raise HTTPException(404, "Profile not found")
        return services.list_notifications(prof.id, unread_only=unread_only)

@notifications.patch("/{notification_id}/read")
def api_mark_notification_read(notification_id: str, actor: str):
    with services._session() as db:
        prof = services._get_profile_by_name(db, actor)
        actor_profile_id = prof.id if prof else None
    if not services.mark_notification_read(notification_id, actor_profile_id=actor_profile_id):
        raise HTTPException(404, "Notification not found or not yours")
    return {"ok": True}


# ── Webhooks Router ─────────────────────────────────────────────────────

webhooks = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

@webhooks.post("/github")
async def api_github_webhook(request: Request):
    body = await request.json()
    results = services.process_github_webhook(body)
    return {"linked": len(results), "items": results}


# ── App Assembly ─────────────────────────────────────────────────────────

app = FastAPI(title="AgentIRA", version="0.2.0", description="Lean task manager for AI agents")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Register all routers
for r in [auth, profiles, svc_accounts, projects, tasks, attachments, workflow, notifications, webhooks, epics_router]:
    app.include_router(r)

# Forge product router (self-contained)
from backend.forge.router import router as forge_router
app.include_router(forge_router)

# Legacy compat: /api/board/{project_id} → /api/projects/{project_id}/board
@app.get("/api/board/{project_id}", tags=["projects"], include_in_schema=False)
def api_board_legacy(project_id: str):
    try:
        return services.get_board(project_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.get("/api/epics/", tags=["epics"])
@app.get("/api/epics", tags=["epics"])
def api_list_all_epics(project_id: Optional[str] = None, actor: str = "system"):
    print(f"[DEBUG] api_list_all_epics project_id={project_id}")
    return services.list_epics(project_id=project_id, actor=actor)

@app.on_event("startup")
def startup():
    from backend.db import init_db
    init_db()
