"""FastAPI REST API — entity-level routers, thin wrapper around services."""

from __future__ import annotations
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, APIRouter, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import os
import httpx
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from backend import services
from backend.jwt_auth import create_token, get_current_user

# ── Schemas ──────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class ProfileSignup(BaseModel):
    name: str
    display_name: str = ""
    password: str

class GoogleAuthRequest(BaseModel):
    id_token: str

class GitHubAuthRequest(BaseModel):
    code: str

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

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    repo_path: Optional[str] = None
    repo_url: Optional[str] = None
    conventions_md: Optional[str] = None
    # ADR 009 / AP-136: run-crystallization work-signal mode.
    work_signal: Optional[str] = None

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

class TaskMove(BaseModel):
    status: str

class CommentCreate(BaseModel):
    comment: str

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

class EpicUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None

class WebhookRuleSchema(BaseModel):
    event: str
    receivers: str

class WebhookConfigUpdate(BaseModel):
    enabled: bool = True
    rules: list[WebhookRuleSchema] = Field(default_factory=list)
    token: str = ""


def _make_token(user: dict) -> str:
    """Create a JWT from a user dict returned by services."""
    role = user.get("role", "member")
    if isinstance(role, dict):
        role = role.get("name", "member")
    return create_token(user["name"], user["id"], role)


# ── Auth Router (PUBLIC — no JWT required) ───────────────────────────────

auth = APIRouter(prefix="/api", tags=["auth"])

@auth.post("/login")
def api_login(body: LoginRequest):
    user = services.authenticate_user(body.username, body.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    return {"user": user, "token": _make_token(user)}

@auth.post("/signup")
def api_signup(body: ProfileSignup):
    try:
        user = services.signup(body.name, body.display_name, body.password)
        return {"user": user, "token": _make_token(user)}
    except Exception as e:
        raise HTTPException(400, str(e))


@auth.post("/auth/google")
def api_auth_google(body: GoogleAuthRequest):
    """Verify a Google ID token and log in / auto-register the user."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(500, "Google OAuth is not configured")
    try:
        info = google_id_token.verify_oauth2_token(
            body.id_token, google_requests.Request(), client_id
        )
    except Exception:
        raise HTTPException(401, "Invalid Google token")

    user = services.authenticate_oauth(
        provider="google",
        provider_user_id=info["sub"],
        email=info.get("email"),
        display_name=info.get("name", ""),
        avatar_url=info.get("picture", ""),
    )
    return {"user": user, "token": _make_token(user)}


@auth.post("/auth/github")
async def api_auth_github(body: GitHubAuthRequest):
    """Exchange a GitHub OAuth code for user info and log in / auto-register."""
    client_id = os.getenv("GITHUB_CLIENT_ID", "")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(500, "GitHub OAuth is not configured")

    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={"client_id": client_id, "client_secret": client_secret, "code": body.code},
            headers={"Accept": "application/json"},
        )
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(401, "GitHub OAuth failed")

        # Get user info
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        gh_user = user_resp.json()

        # Get primary email if not public
        email = gh_user.get("email")
        if not email:
            emails_resp = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            for e in emails_resp.json():
                if e.get("primary"):
                    email = e["email"]
                    break

    user = services.authenticate_oauth(
        provider="github",
        provider_user_id=str(gh_user["id"]),
        email=email,
        display_name=gh_user.get("name") or gh_user.get("login", ""),
        avatar_url=gh_user.get("avatar_url", ""),
    )
    return {"user": user, "token": _make_token(user)}


@auth.get("/auth/config")
def api_auth_config():
    """Return which OAuth providers are enabled and their public client IDs."""
    return {
        "google": bool(os.getenv("GOOGLE_CLIENT_ID")),
        "google_client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "github": bool(os.getenv("GITHUB_CLIENT_ID")),
        "github_client_id": os.getenv("GITHUB_CLIENT_ID", ""),
    }

@auth.get("/statuses")
def api_list_statuses():
    return services.list_statuses()


# ── Profiles Router ──────────────────────────────────────────────────────

profiles = APIRouter(prefix="/api/profiles", tags=["profiles"],
                     dependencies=[Depends(get_current_user)])

@profiles.get("/me")
def api_get_me(actor: str = Depends(get_current_user)):
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
svc_accounts = APIRouter(prefix="/api/service-accounts", tags=["profiles"],
                         dependencies=[Depends(get_current_user)])

@svc_accounts.get("")
def api_list_service_accounts():
    return services.list_service_accounts()

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
    # Block leakage of managed agents (bot + runtime_id) through this endpoint.
    if result.get("runtime_id"):
        raise HTTPException(404, "Not a service account")
    return result

@svc_accounts.delete("/{profile_id}")
def api_delete_service_account(profile_id: str):
    if not services.delete_profile(profile_id):
        raise HTTPException(404, "Profile not found")
    return {"ok": True}


# ── Projects Router ──────────────────────────────────────────────────────

projects = APIRouter(prefix="/api/projects", tags=["projects"],
                     dependencies=[Depends(get_current_user)])

@projects.get("")
def api_list_projects(actor: str = Depends(get_current_user)):
    return services.list_projects(actor=actor)

@projects.post("")
def api_create_project(body: ProjectCreate, actor: str = Depends(get_current_user)):
    return services.create_project(body.name, body.description, actor=actor)

@projects.get("/{project_id}")
def api_get_project(project_id: str):
    result = services.get_project(project_id)
    if not result:
        raise HTTPException(404, "Project not found")
    return result

@projects.patch("/{project_id}")
def api_update_project(project_id: str, body: ProjectUpdate):
    try:
        return services.update_project(
            project_id,
            name=body.name,
            description=body.description,
            repo_path=body.repo_path,
            conventions_md=body.conventions_md,
            work_signal=body.work_signal,
        )
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
def api_add_project_member(project_id: str, body: dict, actor: str = Depends(get_current_user)):
    try:
        return services.add_project_member(project_id, body["profile_name"], actor=actor)
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
def api_create_epic(project_id: str, body: EpicCreate, actor: str = Depends(get_current_user)):
    try:
        return services.create_epic(project_id, title=body.title, description=body.description, color=body.color, actor=actor)
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


# ── AP-121: Project repos REST surface ───────────────────────────────────
# Backend services + MCP tool shipped in #74. This adds the thin REST
# wrappers the browser UI needs (the browser can't call MCP directly).

class ProjectRepoCreate(BaseModel):
    name: str
    repo_path: str = ""
    repo_url: str = ""
    default_branch: str = "main"
    is_primary: bool = False


@projects.get("/{project_id}/repos")
def api_list_project_repos(project_id: str):
    return services.list_project_repos(project_id)


@projects.post("/{project_id}/repos")
def api_add_project_repo(project_id: str, body: ProjectRepoCreate):
    res = services.add_project_repo(
        project_id, name=body.name,
        repo_path=body.repo_path, repo_url=body.repo_url,
        default_branch=body.default_branch,
        is_primary=body.is_primary,
    )
    if "error" in res:
        raise HTTPException(400, res["error"])
    return res


@projects.delete("/{project_id}/repos/{repo_name}")
def api_remove_project_repo(project_id: str, repo_name: str):
    if not services.remove_project_repo(project_id, repo_name):
        raise HTTPException(404, "Repo not found")
    return {"ok": True}


# ── Tasks Router ─────────────────────────────────────────────────────────

tasks = APIRouter(prefix="/api/tasks", tags=["tasks"],
                  dependencies=[Depends(get_current_user)])

@tasks.get("")
def api_list_tasks(
    project_id: Optional[str] = None, status: Optional[str] = None,
    assignee: Optional[str] = None, priority: Optional[str] = None,
    actor: str = Depends(get_current_user),
):
    return services.list_tasks(project_id=project_id, status=status, assignee=assignee, priority=priority, actor=actor)

@tasks.post("")
def api_create_task(body: TaskCreate, actor: str = Depends(get_current_user)):
    try:
        return services.create_task(
            project_id=body.project_id, title=body.title, description=body.description,
            status=body.status, priority=body.priority, assignee=body.assignee,
            tags=body.tags, start_date=body.start_date, due_date=body.due_date,
            epic_id=body.epic_id, actor=actor,
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
def api_update_task(task_id: str, body: TaskUpdate, actor: str = Depends(get_current_user)):
    try:
        result = services.update_task(
            task_id=task_id, title=body.title, description=body.description,
            priority=body.priority, assignee=body.assignee, tags=body.tags,
            start_date=body.start_date, due_date=body.due_date,
            dod_items=body.dod_items, branch=body.branch, pr_url=body.pr_url,
            epic_id=body.epic_id, actor=actor,
        )
        if body.assignee:
            try:
                from backend.forge.triggers import fire_task_assigned
                fire_task_assigned(task_id=task_id, assignee_name=body.assignee)
            except Exception:
                pass  # never break task update due to WS dispatch
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))

@tasks.delete("/{task_id}")
def api_delete_task(task_id: str):
    if not services.delete_task(task_id):
        raise HTTPException(404, "Task not found")
    return {"ok": True}

@tasks.post("/{task_id}/move")
def api_move_task(task_id: str, body: TaskMove, actor: str = Depends(get_current_user)):
    try:
        return services.move_task(task_id, body.status, actor)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

@tasks.post("/{task_id}/comment")
def api_add_comment(task_id: str, body: CommentCreate, actor: str = Depends(get_current_user)):
    try:
        return services.add_comment(task_id, body.comment, actor)
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
async def api_upload_attachment(task_id: str, file: UploadFile = File(...), actor: str = Depends(get_current_user)):
    try:
        file_bytes = await file.read()
        return services.add_attachment(task_id=task_id, filename=file.filename, file_bytes=file_bytes,
                                       content_type=file.content_type or "application/octet-stream", uploaded_by=actor)
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

attachments = APIRouter(prefix="/api/attachments", tags=["tasks"],
                        dependencies=[Depends(get_current_user)])

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

epics_router = APIRouter(prefix="/api/epics", tags=["epics"],
                         dependencies=[Depends(get_current_user)])

@epics_router.get("/{epic_id}")
def api_get_epic(epic_id: str):
    epic = services.get_epic(epic_id)
    if not epic:
        raise HTTPException(404, "Epic not found")
    return epic


@epics_router.get("/{epic_id}/tasks")
def api_list_epic_tasks(epic_id: str):
    return services.list_epic_tasks(epic_id)


@epics_router.patch("/{epic_id}")
def api_update_epic(epic_id: str, body: EpicUpdate, actor: str = Depends(get_current_user)):
    try:
        return services.update_epic(epic_id, title=body.title, description=body.description, color=body.color, actor=actor)
    except ValueError as e:
        raise HTTPException(404, str(e))

@epics_router.delete("/{epic_id}")
def api_delete_epic(epic_id: str):
    if not services.delete_epic(epic_id):
        raise HTTPException(404, "Epic not found")
    return {"ok": True}


# ── Workflow Router (roles, permissions) ─────────────────────────────────

workflow = APIRouter(prefix="/api", tags=["workflow"],
                     dependencies=[Depends(get_current_user)])

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

notifications = APIRouter(prefix="/api/notifications", tags=["notifications"],
                          dependencies=[Depends(get_current_user)])

@notifications.get("")
def api_list_notifications(actor: str = Depends(get_current_user), unread_only: bool = True):
    with services._session() as db:
        prof = services._get_profile_by_name(db, actor)
        if not prof:
            raise HTTPException(404, "Profile not found")
        return services.list_notifications(prof.id, unread_only=unread_only)

@notifications.patch("/{notification_id}/read")
def api_mark_notification_read(notification_id: str, actor: str = Depends(get_current_user)):
    with services._session() as db:
        prof = services._get_profile_by_name(db, actor)
        actor_profile_id = prof.id if prof else None
    if not services.mark_notification_read(notification_id, actor_profile_id=actor_profile_id):
        raise HTTPException(404, "Notification not found or not yours")
    return {"ok": True}


# ── Webhooks Router (PUBLIC — external webhooks) ─────────────────────────

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
from backend.forge.router import router as forge_router, daemon_router as forge_daemon_router
app.include_router(forge_router, dependencies=[Depends(get_current_user)])
app.include_router(forge_daemon_router)  # daemon-facing, no user JWT


# Legacy compat: /api/board/{project_id} → /api/projects/{project_id}/board
@app.get("/api/board/{project_id}", tags=["projects"], include_in_schema=False,
         dependencies=[Depends(get_current_user)])
def api_board_legacy(project_id: str):
    try:
        return services.get_board(project_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.get("/api/epics/", tags=["epics"], dependencies=[Depends(get_current_user)])
@app.get("/api/epics", tags=["epics"], dependencies=[Depends(get_current_user)])
def api_list_all_epics(project_id: Optional[str] = None, actor: str = Depends(get_current_user)):
    return services.list_epics(project_id=project_id, actor=actor)

@app.on_event("startup")
async def startup():
    from backend.db import init_db
    init_db()
    # Capture the main event loop so the Conductor (which ticks in an
    # APScheduler background thread) can marshal dispatch coroutines
    # onto it — the WS hub's sockets are bound to this loop.
    try:
        import asyncio
        from backend.forge import services as _forge_services
        _forge_services.set_main_loop(asyncio.get_running_loop())
    except Exception as exc:
        import logging
        logging.getLogger("agentira").warning("Could not capture main loop: %s", exc)
    try:
        from backend.forge.scheduler import scheduler
        scheduler.start()
    except Exception as exc:
        import logging
        logging.getLogger("agentira").warning("Scheduler failed to start: %s", exc)


@app.on_event("shutdown")
def shutdown():
    try:
        from backend.forge.scheduler import scheduler
        scheduler.stop()
    except Exception:
        pass
