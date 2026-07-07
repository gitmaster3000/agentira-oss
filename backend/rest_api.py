"""FastAPI REST API — entity-level routers, thin wrapper around services."""

from __future__ import annotations
from typing import Optional, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, APIRouter, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import os
import httpx
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from backend import services
from backend.password_service import password_service
from backend.jwt_auth import (create_token, get_current_user, require_admin,
                              get_current_user_payload)

# ── Schemas ──────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class ProfileSignup(BaseModel):
    name: str
    display_name: str = ""
    password: str
    email: str  # AP-306: every account must carry an email

class GoogleAuthRequest(BaseModel):
    id_token: str
    invite: str | None = None

class GitHubAuthRequest(BaseModel):
    code: str
    invite: str | None = None

class ProfileCreate(BaseModel):
    name: str
    display_name: str = ""
    role: str = "member"
    avatar_url: str = ""

class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None          # legacy single-role (still accepted)
    roles: Optional[List[str]] = None   # RBAC: assign one or more roles
    avatar_url: Optional[str] = None
    webhook_url: Optional[str] = None
    email: Optional[str] = None  # AP-306: admin sets/backfills a member's email

# AP-306: password lifecycle request bodies.
class AdminSetPasswordBody(BaseModel):
    new_password: Optional[str] = None  # omit → server generates a temp password

class ChangePasswordBody(BaseModel):
    new_password: str

class ForgotPasswordBody(BaseModel):
    email: str

class ResetPasswordBody(BaseModel):
    token: str
    new_password: str

# AP-302: git access token (PAT) for a project repo or an agent/user.
# Empty string clears the stored token. Value is write-only — never echoed.
class RepoTokenBody(BaseModel):
    token: str = ""

class InitialTaskSpec(BaseModel):
    title: str
    description: str = ""
    assignee: str = ""
    priority: str = "medium"
    status: str = "todo"

class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    # AP-153 wizard payload. Both omitted → legacy auto-seed
    # (Conductor + empty "Plan this project" task). Either present
    # (even empty list) → wizard mode: user owns membership + tasks.
    initial_tasks: Optional[list[InitialTaskSpec]] = None
    members: Optional[list[str]] = None
    # Seed the default "professionalization" backlog (logging, tests, security,
    # CI/CD) the user can then run with the Conductor.
    seed_defaults: bool = False

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    repo_path: Optional[str] = None
    repo_url: Optional[str] = None
    # AP-197: "git" | "sandbox" | "local_folder" ("" = infer from repo fields).
    workspace_kind: Optional[str] = None
    conventions_md: Optional[str] = None
    # ADR 009 / AP-136: run-crystallization work-signal mode.
    work_signal: Optional[str] = None
    # AP-155: project-level sandbox containment override. NULL → inherit
    # from the dispatched agent's `Profile.sandbox_mode`.
    sandbox_mode: Optional[str] = None
    # AP-308: per-run environment isolation. "" / "auto" = resolved at
    # dispatch; "hermetic" | "per_run_db" | "per_run_compose" force a mode.
    # The override cmds/url are advanced knobs (built-in defaults daemon-side).
    env_isolation: Optional[str] = None
    env_setup_cmd: Optional[str] = None
    env_teardown_cmd: Optional[str] = None
    env_db_admin_url: Optional[str] = None
    # AP-158: column-exit gate enforcement.
    gates_enabled: Optional[bool] = None
    # AP-184: when on, any comment wakes the assigned agent (legacy). Off
    # (default) = only @mention wakes; a plain comment is recorded as context.
    wake_on_comment: Optional[bool] = None
    # Workflow driver opt-in + the restricted role->agent override (the flow
    # itself is system config; see templates/workflow/default.yaml).
    workflow_enabled: Optional[bool] = None
    workflow_roles_json: Optional[str] = None
    # AP-297: TTL (seconds) for cached pre-run checks. null = no change;
    # negative resets to the default (600s); 0 = never expire by age.
    ready_checks_ttl_seconds: Optional[int] = None

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
    dod_items: Optional[list[dict]] = None
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
    # AP-154: declared repos this task touches (subset of project_repos.name).
    # Empty/omitted → derive from the task's legacy `repo_name` or fall back
    # to the project's primary.
    repos: Optional[list[str]] = None

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

class EpicPlanRequest(BaseModel):
    agent_id: str
    prompt: Optional[str] = None

class WebhookRuleSchema(BaseModel):
    event: str
    receivers: str

class WebhookConfigUpdate(BaseModel):
    enabled: bool = True
    rules: list[WebhookRuleSchema] = Field(default_factory=list)
    token: str = ""


def _make_token(user: dict) -> str:
    """Create a JWT from a user dict returned by services."""
    roles = user.get("roles")
    if not roles:
        role = user.get("role", "member")
        if isinstance(role, dict):
            role = role.get("name", "member")
        roles = [role]
    return create_token(user["name"], user["id"], roles, user.get("org_id"))


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
    # Open self-serve signup is disabled — accounts are invite-only.
    raise HTTPException(403, "Signup is invite-only. Ask your admin for an invite link.")


# ── AP-306: forgot/reset password (PUBLIC) ───────────────────────────────

@auth.post("/auth/forgot-password")
def api_forgot_password(body: ForgotPasswordBody):
    """Always 200 — never reveal whether an email is registered."""
    password_service.request_reset(body.email)
    return {"ok": True}

@auth.post("/auth/reset-password")
def api_reset_password(body: ResetPasswordBody):
    if not password_service.reset_with_token(body.token, body.new_password):
        raise HTTPException(400, "Invalid or expired reset link")
    return {"ok": True}


# ── Invites ──────────────────────────────────────────────────────────────

@auth.get("/invites/{code}")
def api_get_invite(code: str):
    """Public: describe an invite so the signup page can render it."""
    inv = services.get_invite(code)
    if not inv:
        raise HTTPException(404, "Invite not found")
    if inv["accepted"]:
        raise HTTPException(410, "Invite already used")
    if inv["expired"]:
        raise HTTPException(410, "Invite expired")
    return inv


@auth.post("/invites/{code}/accept")
def api_accept_invite(code: str, body: ProfileSignup):
    """Public: accept an invite, creating the account."""
    try:
        user = services.accept_invite(
            code, name=body.name, password=body.password,
            display_name=body.display_name or "", email=body.email)
        return {"user": user, "token": _make_token(user)}
    except ValueError as e:
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

    try:
        user = services.authenticate_oauth(
            provider="google",
            provider_user_id=info["sub"],
            email=info.get("email"),
            display_name=info.get("name", ""),
            avatar_url=info.get("picture", ""),
            invite_code=body.invite,
        )
    except ValueError as e:
        raise HTTPException(403, str(e))
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

        # Get primary email — only trust a VERIFIED one. An unverified email
        # would let an attacker set a victim's address and link into their
        # account/org (account takeover).
        email = None
        emails_resp = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        for e in emails_resp.json():
            if e.get("primary") and e.get("verified"):
                email = e["email"]
                break

    try:
        user = services.authenticate_oauth(
            provider="github",
            provider_user_id=str(gh_user["id"]),
            email=email,
            display_name=gh_user.get("name") or gh_user.get("login", ""),
            avatar_url=gh_user.get("avatar_url", ""),
            invite_code=body.invite,
        )
    except ValueError as e:
        raise HTTPException(403, str(e))
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


# ── Daemon browser login (device-code flow) ──────────────────────────────
# `agentira daemon login` opens the browser; the admin approves in-app; the
# daemon polls for the resulting admin token. Admin-only: a daemon runs with
# an admin identity so its runtime registration is org-scoped. Sessions live
# in-process (short-lived; single replica) — fine for current scale.
import secrets as _secrets, time as _time  # noqa: E402

_CLI_SESSIONS: dict = {}          # device_code -> {user_code, status, token, exp}
_CLI_BY_USER_CODE: dict = {}      # user_code   -> device_code
_CLI_TTL = 600                    # 10 minutes

def _cli_gc():
    now = _time.time()
    for dc in [k for k, v in _CLI_SESSIONS.items() if v["exp"] < now]:
        uc = _CLI_SESSIONS.pop(dc, {}).get("user_code")
        _CLI_BY_USER_CODE.pop(uc, None)

@auth.post("/auth/cli/start")
def api_cli_start():
    """Daemon → start a browser-login session."""
    _cli_gc()
    device_code = _secrets.token_urlsafe(32)
    # Pre-filled in the verification URL, so it can be high-entropy (not a
    # 6-char code an attacker could brute-force against a pending session).
    user_code = _secrets.token_urlsafe(16)
    _CLI_SESSIONS[device_code] = {"user_code": user_code, "status": "pending",
                                  "token": None, "exp": _time.time() + _CLI_TTL}
    _CLI_BY_USER_CODE[user_code] = device_code
    frontend = (os.getenv("FRONTEND_URL", "") or
                (os.getenv("CORS_ALLOW_ORIGINS", "").split(",")[0] if os.getenv("CORS_ALLOW_ORIGINS") else "")).rstrip("/")
    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_uri": f"{frontend}/cli-auth" if frontend else "/cli-auth",
        "interval": 2,
        "expires_in": _CLI_TTL,
    }

@auth.post("/auth/cli/poll")
def api_cli_poll(body: dict):
    """Daemon → poll until approved; returns the admin token once granted."""
    _cli_gc()
    s = _CLI_SESSIONS.get((body or {}).get("device_code", ""))
    if not s:
        raise HTTPException(404, "expired_or_unknown")
    if s["status"] == "approved":
        token = s["token"]
        # one-time: invalidate after handing the token over
        _CLI_BY_USER_CODE.pop(s["user_code"], None)
        _CLI_SESSIONS.pop(body["device_code"], None)
        return {"status": "approved", "token": token}
    return {"status": s["status"]}

@auth.post("/auth/cli/approve", dependencies=[Depends(require_admin)])
def api_cli_approve(body: dict, payload: dict = Depends(get_current_user_payload)):
    """Admin (in-app) → approve a daemon login, minting an admin token bound to
    the admin's org."""
    _cli_gc()
    user_code = (body or {}).get("user_code", "").strip()
    dc = _CLI_BY_USER_CODE.get(user_code)
    s = _CLI_SESSIONS.get(dc) if dc else None
    if not s:
        raise HTTPException(404, "Invalid or expired code")
    s["status"] = "approved"
    from backend.jwt_auth import payload_roles
    s["token"] = create_token(payload["sub"], payload["profile_id"],
                              payload_roles(payload) or ["admin"], payload.get("org_id"))
    return {"ok": True}

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

@profiles.post("", dependencies=[Depends(require_admin)])
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

@profiles.patch("/{profile_id}", dependencies=[Depends(require_admin)])
def api_update_profile(profile_id: str, body: ProfileUpdate):
    try:
        return services.update_profile(profile_id, display_name=body.display_name, role=body.role, roles=body.roles, avatar_url=body.avatar_url, webhook_url=body.webhook_url, email=body.email)
    except ValueError as e:
        # "not found" → 404; validation errors (bad/duplicate email) → 400.
        raise HTTPException(404 if "not found" in str(e).lower() else 400, str(e))

@profiles.delete("/{profile_id}", dependencies=[Depends(require_admin)])
def api_delete_profile(profile_id: str):
    if not services.delete_profile(profile_id):
        raise HTTPException(404, "Profile not found")
    return {"ok": True}

# AP-306: admin sets/resets a member's password (forces change on next login).
@profiles.post("/{profile_id}/reset-password", dependencies=[Depends(require_admin)])
def api_admin_reset_password(profile_id: str, body: AdminSetPasswordBody):
    res = password_service.admin_set_password(profile_id, body.new_password)
    if res is None:
        raise HTTPException(404, "Profile not found")
    return res

# AP-306: logged-in user changes their own password.
@profiles.post("/me/password")
def api_change_own_password(body: ChangePasswordBody, actor: str = Depends(get_current_user)):
    try:
        password_service.change_own_password(actor, body.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# AP-302: agent/user personal git access token. Same shape as the per-repo
# token: PUT stores + probes, check re-probes. Value never returned.
@profiles.put("/{profile_id}/git-token")
def api_set_profile_git_token(profile_id: str, body: RepoTokenBody):
    res = services.set_profile_git_token(profile_id, body.token)
    if res is None:
        raise HTTPException(404, "Profile not found")
    return res


@profiles.post("/{profile_id}/git-token/check")
def api_check_profile_git_token(profile_id: str):
    res = services.check_profile_git_token(profile_id)
    if res is None:
        raise HTTPException(404, "Profile not found")
    return res

# Service accounts = profiles with role=bot. Admin-only: api_key is sensitive
# and the surface is workspace-global (no per-owner concept in the schema).
svc_accounts = APIRouter(prefix="/api/service-accounts", tags=["profiles"],
                         dependencies=[Depends(require_admin)])

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

@svc_accounts.post("/{profile_id}/regenerate-key")
def api_regenerate_service_account_key(profile_id: str):
    result = services.regenerate_api_key(profile_id)
    if not result:
        raise HTTPException(404, "Service account not found")
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
    initial_tasks = (
        [t.model_dump() for t in body.initial_tasks]
        if body.initial_tasks is not None else None
    )
    return services.create_project(
        body.name, body.description, actor=actor,
        initial_tasks=initial_tasks,
        members=body.members,
        seed_defaults=body.seed_defaults,
    )

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
            repo_url=body.repo_url,
            workspace_kind=body.workspace_kind,
            conventions_md=body.conventions_md,
            work_signal=body.work_signal,
            sandbox_mode=body.sandbox_mode,
            env_isolation=body.env_isolation,
            env_setup_cmd=body.env_setup_cmd,
            env_teardown_cmd=body.env_teardown_cmd,
            env_db_admin_url=body.env_db_admin_url,
            gates_enabled=body.gates_enabled,
            wake_on_comment=body.wake_on_comment,
            workflow_enabled=body.workflow_enabled,
            workflow_roles_json=body.workflow_roles_json,
            ready_checks_ttl_seconds=body.ready_checks_ttl_seconds,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

@projects.get("/{project_id}/workflow")
def api_get_project_workflow(project_id: str):
    """The project's EFFECTIVE workflow — system flow + its role overrides.
    Read-only transparency surface: customers see exactly how tasks will move
    and who picks up each column; they edit only roles (via PATCH project's
    workflow_roles_json), never the flow."""
    from backend.db import SessionLocal
    from backend.models import Project
    from backend.forge import workflow as _workflow
    with SessionLocal() as db:
        p = db.get(Project, project_id)
        if not p:
            raise HTTPException(404, "Project not found")
        flow = _workflow.effective_workflow(p)
        return {
            "workflow_enabled": bool(getattr(p, "workflow_enabled", False)),
            "flow": flow.model_dump(),
            "columns_ui": _workflow.column_ui_details(flow),
            "editable": ["workflow_enabled", "workflow_roles_json"],
        }

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


# AP-152: project-level attachments. Same Attachment table as tasks
# (FK swapped); shared `/api/attachments/{id}/download` and DELETE
# endpoints above handle either side.
@projects.get("/{project_id}/attachments")
def api_list_project_attachments(project_id: str):
    from backend import attachments as _attachments
    return _attachments.list_for_project(project_id)


@projects.post("/{project_id}/attachments")
async def api_upload_project_attachment(project_id: str, file: UploadFile = File(...),
                                         extract: bool = False,
                                         actor: str = Depends(get_current_user)):
    """Upload a single file. With `?extract=true` a .zip is unpacked and its
    contents stored as a folder (preserving structure)."""
    from backend import attachments as _attachments
    try:
        file_bytes = await file.read()
        if extract:
            return _attachments.add_zip(
                project_id=project_id, zip_bytes=file_bytes, uploaded_by=actor,
            )
        return _attachments.add(
            project_id=project_id, filename=file.filename, file_bytes=file_bytes,
            content_type=file.content_type or "application/octet-stream",
            uploaded_by=actor,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@projects.post("/{project_id}/attachments/folder")
async def api_upload_project_folder(
    project_id: str,
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
    actor: str = Depends(get_current_user),
):
    """Folder upload. `files[i]` is stored under its `paths[i]` relative path
    (browser `webkitRelativePath`)."""
    from backend import attachments as _attachments
    if len(files) != len(paths):
        raise HTTPException(400, "files and paths must have equal length")
    try:
        specs = [
            {
                "relative_path": p,
                "file_bytes": await f.read(),
                "content_type": f.content_type or "application/octet-stream",
            }
            for f, p in zip(files, paths)
        ]
        return _attachments.add_folder(
            project_id=project_id, files=specs, uploaded_by=actor,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

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


class ProjectRepoUpdate(BaseModel):
    # AP-197: connect/update a repo's remote so the daemon clones it.
    repo_url: Optional[str] = None
    repo_path: Optional[str] = None
    default_branch: Optional[str] = None


@projects.patch("/{project_id}/repos/{repo_name}")
def api_update_project_repo(project_id: str, repo_name: str,
                            body: ProjectRepoUpdate):
    res = services.update_project_repo(
        project_id, repo_name,
        repo_url=body.repo_url, repo_path=body.repo_path,
        default_branch=body.default_branch,
    )
    if "error" in res:
        code = 404 if "not found" in res["error"] else 400
        raise HTTPException(code, res["error"])
    return res


@projects.delete("/{project_id}/repos/{repo_name}")
def api_remove_project_repo(project_id: str, repo_name: str):
    if not services.remove_project_repo(project_id, repo_name):
        raise HTTPException(404, "Repo not found")
    return {"ok": True}


@projects.put("/{project_id}/repos/{repo_name}/token")
def api_set_project_repo_token(project_id: str, repo_name: str,
                               body: RepoTokenBody):
    res = services.set_project_repo_token(project_id, repo_name, body.token)
    if res is None:
        raise HTTPException(404, "Repo not found")
    return res


@projects.post("/{project_id}/repos/{repo_name}/token/check")
def api_check_project_repo_token(project_id: str, repo_name: str):
    res = services.check_project_repo_token(project_id, repo_name)
    if res is None:
        raise HTTPException(404, "Repo not found")
    return res


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
            dod_items=body.dod_items, epic_id=body.epic_id, actor=actor,
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
            epic_id=body.epic_id, repos=body.repos, actor=actor,
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
    from backend.gates import GateFailure
    try:
        return services.move_task(task_id, body.status, actor)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except GateFailure as e:
        # AP-158: structured 422 so the UI can surface each failed gate
        # with its name + reason rather than a one-line message.
        raise HTTPException(422, detail=e.to_dict())
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
async def api_upload_attachment(task_id: str, file: UploadFile = File(...),
                                extract: bool = False,
                                actor: str = Depends(get_current_user)):
    """Upload a single file. With `?extract=true` a .zip is unpacked and its
    contents stored as a folder (preserving structure)."""
    try:
        file_bytes = await file.read()
        if extract:
            from backend import attachments as _attachments
            return _attachments.add_zip(task_id=task_id, zip_bytes=file_bytes, uploaded_by=actor)
        return services.add_attachment(task_id=task_id, filename=file.filename, file_bytes=file_bytes,
                                       content_type=file.content_type or "application/octet-stream", uploaded_by=actor)
    except ValueError as e:
        raise HTTPException(404, str(e))


@tasks.post("/{task_id}/attachments/folder")
async def api_upload_task_folder(
    task_id: str,
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
    actor: str = Depends(get_current_user),
):
    """Folder upload for a task. `files[i]` is stored under its `paths[i]`
    relative path (browser `webkitRelativePath`)."""
    from backend import attachments as _attachments
    if len(files) != len(paths):
        raise HTTPException(400, "files and paths must have equal length")
    try:
        specs = [
            {
                "relative_path": p,
                "file_bytes": await f.read(),
                "content_type": f.content_type or "application/octet-stream",
            }
            for f, p in zip(files, paths)
        ]
        return _attachments.add_folder(task_id=task_id, files=specs, uploaded_by=actor)
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


# AP-351: epic planning — the editable default prompt for the modal, and the
# action that prepares an "Epic Planning" run.
@epics_router.get("/{epic_id}/plan-template")
def api_get_epic_plan_template(epic_id: str):
    epic = services.get_epic(epic_id)
    if not epic:
        raise HTTPException(404, "Epic not found")
    from backend.forge import epic_planning
    return {"prompt": epic_planning.default_plan_prompt(epic)}


@epics_router.post("/{epic_id}/plan", status_code=201)
def api_plan_epic(epic_id: str, body: EpicPlanRequest):
    from backend.forge import services as _forge_services
    result = _forge_services.prepare_epic_plan_run(
        epic_id=epic_id, agent_id=body.agent_id, prompt=body.prompt)
    if result.get("error"):
        code = 404 if result["error"] in ("Epic not found", "Task not found",
                                          "Agent not found") else 400
        raise HTTPException(code, result["error"])
    return result


# AP-351: epic-scoped attachments. Same Attachment table + shared
# /api/attachments/{id}/{download,delete} endpoints handle either side.
@epics_router.get("/{epic_id}/attachments")
def api_list_epic_attachments(epic_id: str):
    from backend import attachments as _attachments
    return _attachments.list_for_epic(epic_id)


@epics_router.post("/{epic_id}/attachments")
async def api_upload_epic_attachment(epic_id: str, file: UploadFile = File(...),
                                     extract: bool = False,
                                     actor: str = Depends(get_current_user)):
    """Upload a single file. With `?extract=true` a .zip is unpacked and its
    contents stored as a folder (preserving structure)."""
    from backend import attachments as _attachments
    try:
        file_bytes = await file.read()
        if extract:
            return _attachments.add_zip(
                epic_id=epic_id, zip_bytes=file_bytes, uploaded_by=actor)
        return _attachments.add(
            epic_id=epic_id, filename=file.filename, file_bytes=file_bytes,
            content_type=file.content_type or "application/octet-stream",
            uploaded_by=actor)
    except ValueError as e:
        raise HTTPException(404, str(e))


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
def api_list_notifications(actor: str = Depends(get_current_user), unread_only: bool = True,
                           limit: int = Query(100, ge=1, le=200)):
    with services._session() as db:
        prof = services._get_profile_by_name(db, actor)
        if not prof:
            raise HTTPException(404, "Profile not found")
        return services.list_notifications(prof.id, unread_only=unread_only, limit=limit)

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
    # This endpoint is public + runs unscoped, so it MUST verify GitHub's HMAC
    # signature — otherwise anyone could inject commit/PR links into tasks.
    import hmac as _hmac, hashlib as _hashlib, json as _json
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(503, "GitHub webhook not configured")
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + _hmac.new(secret.encode(), raw, _hashlib.sha256).hexdigest()
    if not (sig and _hmac.compare_digest(sig, expected)):
        raise HTTPException(401, "Invalid signature")
    results = services.process_github_webhook(_json.loads(raw))
    return {"linked": len(results), "items": results}


# ── App Assembly ─────────────────────────────────────────────────────────

app = FastAPI(title="AgentIRA", version="0.2.0", description="Lean task manager for AI agents")

# AP-194: never wildcard-with-credentials. Prod origins come from
# CORS_ALLOW_ORIGINS (comma-separated); dev falls back to localhost ports.
_is_prod = os.getenv("RAILWAY_ENVIRONMENT") is not None
_cors_env = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
if _cors_env:
    _allow_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
elif _is_prod:
    _allow_origins = []  # locked down: set CORS_ALLOW_ORIGINS to open it
    import logging as _logging
    _logging.getLogger("agentira").warning(
        "CORS_ALLOW_ORIGINS unset in production — cross-origin requests will "
        "be blocked. Set it to your frontend origin(s).")
else:
    _allow_origins = [
        "http://localhost:5173", "http://localhost:3111",
        "http://localhost:3112", "http://localhost:3113",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Admin-only: issue member invites for the caller's own org.
admin_invites = APIRouter(prefix="/api/invites", tags=["invites"],
                          dependencies=[Depends(require_admin)])

@admin_invites.post("")
def api_create_member_invite(body: dict = None,
                             payload: dict = Depends(get_current_user_payload)):
    body = body or {}
    try:
        return services.create_invite(
            role="member", org_id=payload.get("org_id"),
            email=body.get("email"), invited_by=payload.get("sub"))
    except ValueError as e:
        raise HTTPException(400, str(e))

# Register all routers
for r in [auth, admin_invites, profiles, svc_accounts, projects, tasks, attachments, workflow, notifications, webhooks, epics_router]:
    app.include_router(r)

# Forge product router (self-contained)
from backend.forge.router import router as forge_router, daemon_router as forge_daemon_router
app.include_router(forge_router, dependencies=[Depends(get_current_user)])
# Daemon HTTP endpoints require an ADMIN JWT (added per-route in the router so
# the WebSocket routes — which auth via their first frame / ?token=, since a WS
# can't carry HTTP deps — are not blocked here). require_admin also pins the
# org context, so runtime registration/heartbeats are scoped to the admin's org.
app.include_router(forge_daemon_router)


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
