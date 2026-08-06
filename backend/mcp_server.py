"""
AgentIRA MCP Server — Streamable HTTP Transport.

Single transport, single endpoint. All agents (Claude Code, Cursor, any IDE,
custom bots) connect via POST /mcp with their unique Bearer API key.

No initialization handshake state to lose. No session-drop bugs.
GET /mcp is reserved for server-initiated push notifications (future use).
"""

import logging
import sys
import traceback
import contextlib
from typing import AsyncIterator
import uvicorn
import contextvars
import os

from mcp.server.fastmcp import FastMCP, Context
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import Response
from starlette.requests import Request
from starlette.routing import Route

from backend import services

# ── Global Actor Context ──────────────────────────────────────────────────────
# Set per-request by the auth middleware; read by tool handlers.
actor_ctx = contextvars.ContextVar("actor", default="system")
# Raw bearer token of the caller. AP-280: attachment tools reuse it to proxy
# upload/read to the backend REST API so bytes land on the backend's volume
# (MCP and backend are separate Railway services with separate filesystems).
token_ctx = contextvars.ContextVar("token", default="")

# ── Logging Setup ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "mcp_server.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("mcp_server")
logger.setLevel(logging.DEBUG)

# ── FastMCP — used for tool registration only, not for transport ───────────────
mcp = FastMCP("AgentIRA")

# ── Auth + Logging Middleware ──────────────────────────────────────────────────
class ASGILoggingMiddleware:
    """
    Per-request middleware that:
    1. Validates the Bearer token and resolves the actor identity.
    2. Rejects unauthenticated requests to /mcp with 401.
    3. Sets actor_ctx so tool handlers can identify who is calling.
    4. Logs every request/response.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        headers = {
            k.decode().lower(): v.decode()
            for k, v in scope.get("headers", [])
            if isinstance(k, bytes) and isinstance(v, bytes)
        }

        logger.info(f"REQ: {method} {path}")
        logger.info(f"Headers: {headers}")

        is_protected = path == "/mcp" or path.startswith("/mcp/")

        auth_header = headers.get("authorization", "")
        actor = "system"
        actor_org = None
        is_authenticated = False

        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                profile_dict = services.validate_api_key(token)
                if profile_dict:
                    actor = profile_dict.get("name", "unknown")
                    actor_org = profile_dict.get("org_id")
                    is_authenticated = True
                    logger.info(f"Resolved actor from token: {actor} (org {actor_org})")
            except Exception as e:
                logger.warning(f"Token validation failed: {e}")

        if is_protected and not is_authenticated:
            logger.warning(f"Unauthorized access attempt to {path}")

            async def _unauthorized(scope, receive, send):
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b'{"error":"Unauthorized","message":"Valid Bearer token required"}',
                })

            return await _unauthorized(scope, receive, send)

        if not is_authenticated:
            logger.debug(f"Public access to: {path}")

        token_reset = actor_ctx.set(actor)
        tok_reset = token_ctx.set(token)
        # Pin the org for the request so RLS scopes every tool call to the
        # caller's org. None for unauthenticated/public paths.
        from backend.db import set_current_org
        set_current_org(actor_org)
        try:
            async def _logging_send(message):
                if message["type"] == "http.response.start":
                    logger.info(f"RES: {message['status']} ({method} {path})")
                await send(message)

            await self.app(scope, receive, _logging_send)
        except Exception:
            logger.error(f"ERR: {method} {path} failed:\n{traceback.format_exc()}")
            raise
        finally:
            actor_ctx.reset(token_reset)
            token_ctx.reset(tok_reset)
            set_current_org(None)


# ── Tool Definitions ───────────────────────────────────────────────────────────

@mcp.tool()
async def get_me(ctx: Context) -> str:
    """Get your own profile details. Uses the verified auth context."""
    actor = actor_ctx.get()
    return f"Hello! You are connected as Client ID: {actor}."

@mcp.tool()
async def update_profile(display_name: str = None, avatar_url: str = None, webhook_url: str = None, ctx: Context = None) -> dict:
    """Update your own profile. Set webhook_url so Agentira can push task events to your runtime."""
    actor = actor_ctx.get()
    with services._session() as db:
        p = services._get_profile_by_name(db, actor)
        if not p:
            raise ValueError(f"Profile not found: {actor}")
        return services.update_profile(p.id, display_name=display_name, avatar_url=avatar_url, webhook_url=webhook_url)

@mcp.tool()
async def login(name: str, password: str) -> str:
    """Login with username and password to get your API Key."""
    user = services.authenticate_user(name, password)
    if not user:
        return {"error": "Invalid credentials"}
    with services._session() as db:
        p = db.query(services.Profile).filter(services.Profile.name == name).first()
        res = services._profile_to_dict(p)
        res["api_key"] = p.api_key
        return res

# ── Project Tools ──────────────────────────────────────────────────────────────

@mcp.tool()
async def create_project(name: str, description: str = "", ctx: Context = None) -> dict:
    """Create a new project."""
    actor = actor_ctx.get()
    try:
        logger.info(f"Tool create_project called with name='{name}', actor='{actor}'")
        res = services.create_project(name, description, actor=actor)
        logger.debug(f"Tool create_project success: {res}")
        return res
    except Exception as e:
        logger.error(f"Tool create_project failed: {e}\n{traceback.format_exc()}")
        raise

@mcp.tool()
async def list_projects(ctx: Context = None) -> list[dict]:
    """List all projects visible to you."""
    actor = actor_ctx.get()
    return services.list_projects(actor=actor)

@mcp.tool()
async def get_project(project_id: str, ctx: Context = None) -> dict:
    """Get project details."""
    return services.get_project(project_id, actor=actor_ctx.get())

@mcp.tool()
async def update_project(project_id: str, name: str = None, description: str = None, ctx: Context = None) -> dict:
    """Update project metadata."""
    return services.update_project(
        project_id, name, description, actor=actor_ctx.get(),
    )

@mcp.tool()
async def delete_project(project_id: str, ctx: Context = None) -> bool:
    """Delete a project."""
    return services.delete_project(project_id, actor=actor_ctx.get())

@mcp.tool()
async def add_project_member(project_id: str, profile_name: str, ctx: Context = None) -> dict:
    """Add a user to a project."""
    actor = actor_ctx.get()
    return services.add_project_member(project_id, profile_name, actor=actor)

@mcp.tool()
async def remove_project_member(project_id: str, profile_name: str, ctx: Context = None) -> bool:
    """Remove a user from a project."""
    return services.remove_project_member(
        project_id, profile_name, actor=actor_ctx.get(),
    )

# ── Epic Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_epics(project_id: str = None, ctx: Context = None) -> list[dict]:
    """List all epics for a project or all projects."""
    actor = actor_ctx.get()
    return services.list_epics(project_id=project_id, actor=actor)

@mcp.tool()
async def create_epic(project_id: str, title: str, description: str = "", color: str = "#7c4dff", ctx: Context = None) -> dict:
    """Create a new epic."""
    actor = actor_ctx.get()
    return services.create_epic(project_id, title, description=description, color=color, actor=actor)

@mcp.tool()
async def update_epic(epic_id: str, title: str = None, description: str = None, color: str = None, ctx: Context = None) -> dict:
    """Update epic metadata."""
    actor = actor_ctx.get()
    return services.update_epic(epic_id, title=title, description=description, color=color, actor=actor)

@mcp.tool()
async def delete_epic(epic_id: str, ctx: Context = None) -> bool:
    """Delete an epic."""
    return services.delete_epic(epic_id, actor=actor_ctx.get())

# ── Task Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def create_task(
    project_id: str,
    title: str,
    description: str = "",
    status: str = "backlog",
    priority: str = "medium",
    assignee: str = "",
    tags: list[str] = None,
    start_date: str = None,
    due_date: str = None,
    dod_items: list[dict] = None,
    parent_id: str = None,
    milestone_id: str = None,
    ctx: Context = None,
) -> dict:
    """Create a new task in a project. Use dod_items to set a definition-of-done checklist (list of {text, checked}). Use parent_id to create it as a subtask of another task, and milestone_id to count it towards a roadmap milestone (see get_roadmap / list_milestones)."""
    actor = actor_ctx.get()
    try:
        logger.info(f"Tool create_task called for project='{project_id}', title='{title}', actor='{actor}'")
        res = services.create_task(
            project_id, title, description, status, priority, assignee, tags, start_date=start_date, due_date=due_date, dod_items=dod_items, actor=actor,
            parent_id=parent_id, milestone_id=milestone_id,
        )
        logger.debug(f"Tool create_task success: {res}")
        return res
    except Exception as e:
        logger.error(f"Tool create_task failed: {e}\n{traceback.format_exc()}")
        raise

@mcp.tool()
async def list_tasks(
    project_id: str = None,
    status: str = None,
    assignee: str = None,
    priority: str = None,
    ctx: Context = None,
) -> list[dict]:
    """List tasks matching filters."""
    actor = actor_ctx.get()
    return services.list_tasks(project_id, status, assignee, priority, actor=actor)

@mcp.tool()
async def get_task(task_id: str, ctx: Context = None) -> dict | None:
    """Get task details."""
    try:
        logger.info(f"Tool get_task called for task_id='{task_id}'")
        res = services.get_task(task_id, actor=actor_ctx.get())
        if not res:
            logger.warning(f"Tool get_task: Task {task_id} not found")
            return {"error": "Task not found"}
        logger.debug(f"Tool get_task success: {res}")
        return res
    except Exception as e:
        logger.error(f"Tool get_task failed: {e}\n{traceback.format_exc()}")
        raise

@mcp.tool()
async def update_task(
    task_id: str,
    title: str = None,
    description: str = None,
    priority: str = None,
    assignee: str = None,
    tags: list[str] = None,
    start_date: str = None,
    due_date: str = None,
    branch: str = None,
    pr_url: str = None,
    dod_items: list[dict] = None,
    epic_id: str = None,
    parent_id: str = None,
    milestone_id: str = None,
    ctx: Context = None,
) -> dict:
    """Update task metadata. Use branch/pr_url to link git branch or PR. Use dod_items to set definition-of-done checklist (list of {text, checked}). Use start_date/due_date for roadmap planning. Use epic_id to attach to an epic (or empty string to detach). Use parent_id to nest this task under another one, and milestone_id to count it towards a milestone — pass "" to either to detach."""
    actor = actor_ctx.get()
    return services.update_task(task_id, title, description, priority, assignee, tags, start_date=start_date, due_date=due_date, dod_items=dod_items, branch=branch, pr_url=pr_url, epic_id=epic_id, parent_id=parent_id, milestone_id=milestone_id, actor=actor)

@mcp.tool()
async def move_task(task_id: str, status: str, ctx: Context = None) -> dict:
    """Change task status (e.g. move to 'in-progress')."""
    actor = actor_ctx.get()
    return services.move_task(task_id, status, actor=actor)

@mcp.tool()
async def delete_task(task_id: str, ctx: Context = None) -> bool:
    """Delete a task."""
    return services.delete_task(task_id, actor=actor_ctx.get())

# ── Roadmap / task graph (AP-496) ─────────────────────────────────────────────
# An agent that can't read the plan can't work to it. These give the same view
# the Roadmap page has: the schedule, what blocks what, and what's being aimed
# at — plus the writes needed to structure work (subtasks, dependencies,
# milestones) instead of dumping a flat task list.

@mcp.tool()
async def get_roadmap(project_id: str, group_by: str = "epic", ctx: Context = None) -> dict:
    """Read the project roadmap: tasks grouped by epic (or 'tag') with start/due
    dates and progress, the dependency edges between them, every task's
    is_blocked / blocked_by / blocks / subtasks rollup, the project's milestones
    with derived progress, and a summary (total/done/blocked counts).

    Read this before planning or picking up work: a task whose is_blocked is
    true cannot be started yet — finish what it is blocked_by first."""
    actor = actor_ctx.get()
    services.authorize_project_access(project_id, actor, "read")
    return services.get_roadmap(project_id, group_by=group_by)


@mcp.tool()
async def list_subtasks(task_id: str, ctx: Context = None) -> list[dict]:
    """List the direct child tasks of a task (each with its own subtask rollup)."""
    return services.list_subtasks(task_id, actor=actor_ctx.get())


@mcp.tool()
async def list_dependencies(project_id: str, ctx: Context = None) -> list[dict]:
    """List every dependency edge in the project: each row means `task_id` cannot
    start until `depends_on_id` is done."""
    return services.list_dependencies(project_id, actor=actor_ctx.get())


@mcp.tool()
async def add_dependency(project_id: str, task_id: str, depends_on_id: str,
                         ctx: Context = None) -> dict:
    """Declare that `task_id` waits on `depends_on_id`. Idempotent. Rejected if it
    would create a cycle, point at itself, or cross projects."""
    return services.add_dependency(project_id, task_id, depends_on_id,
                                   actor=actor_ctx.get())


@mcp.tool()
async def remove_dependency(project_id: str, dependency_id: str,
                            ctx: Context = None) -> bool:
    """Remove a dependency edge by its id (see list_dependencies)."""
    return services.remove_dependency(project_id, dependency_id, actor=actor_ctx.get())


@mcp.tool()
async def list_milestones(project_id: str, ctx: Context = None) -> list[dict]:
    """List the project's milestones with due dates and derived progress
    (done/total over the tasks linked to each)."""
    return services.list_milestones(project_id, actor=actor_ctx.get())


@mcp.tool()
async def create_milestone(project_id: str, title: str, description: str = "",
                           due_date: str = None, color: str = "#2ecc71",
                           ctx: Context = None) -> dict:
    """Create a dated roadmap milestone (a launch, demo or deadline). Link tasks to
    it with update_task(milestone_id=...) — progress is derived from those tasks."""
    return services.create_milestone(project_id, title=title, description=description,
                                     due_date=due_date, color=color,
                                     actor=actor_ctx.get())


@mcp.tool()
async def update_milestone(project_id: str, milestone_id: str, title: str = None,
                           description: str = None, due_date: str = None,
                           status: str = None, color: str = None,
                           ctx: Context = None) -> dict:
    """Update a milestone. `status` is one of planned | achieved | missed."""
    return services.update_milestone(project_id, milestone_id, title=title,
                                     description=description, due_date=due_date,
                                     status=status, color=color, actor=actor_ctx.get())


@mcp.tool()
async def delete_milestone(project_id: str, milestone_id: str,
                           ctx: Context = None) -> bool:
    """Delete a milestone. Its tasks are unlinked, never deleted."""
    return services.delete_milestone(project_id, milestone_id, actor=actor_ctx.get())


# ── Collaboration Tools ────────────────────────────────────────────────────────

@mcp.tool()
async def add_comment(task_id: str, comment: str, ctx: Context = None) -> dict:
    """Add a comment/activity log to a task."""
    actor = actor_ctx.get()
    return services.add_comment(task_id, comment, actor=actor)

@mcp.tool()
async def get_activity(task_id: str, ctx: Context = None) -> list[dict]:
    """Get activity history and comments for a task."""
    return services.get_activity(task_id, actor=actor_ctx.get())

@mcp.tool()
async def get_task_activity(task_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
    """Get activity history for a task with pagination and structured diffs."""
    return services.get_activity(
        task_id, limit=limit, offset=offset, actor=actor_ctx.get(),
    )

# ── Notification Tools ─────────────────────────────────────────────────────────

@mcp.tool()
async def get_notifications(unread_only: bool = True, ctx: Context = None) -> list[dict]:
    """Get your notifications. Set unread_only=False to see all notifications."""
    actor = actor_ctx.get()
    with services._session() as db:
        prof = services._get_profile_by_name(db, actor)
        if not prof:
            return []
        return services.list_notifications(prof.id, unread_only=unread_only)

@mcp.tool()
async def mark_notification_read(notification_id: str) -> bool:
    """Mark a notification as read by its ID."""
    actor = actor_ctx.get()
    with services._session() as db:
        prof = services._get_profile_by_name(db, actor)
        actor_profile_id = prof.id if prof else None
    return services.mark_notification_read(notification_id, actor_profile_id=actor_profile_id)

# ── Attachment Tools ────────────────────────────────────────────────────────────
# AP-280: MCP and backend are separate Railway services with separate
# filesystems (volumes are single-service). Writing/reading attachment bytes
# on the MCP container's own disk means the backend download route 404s and the
# bytes vanish on MCP restart. When AGENTIRA_API_BASE_URL is set we proxy
# upload/read to the backend REST API (using the caller's bearer token) so bytes
# land on the backend's persistent volume — the single source of truth. Unset
# (local/dev, where docker-compose shares one volume) keeps the direct path.


def _api_base() -> str:
    return os.getenv("AGENTIRA_API_BASE_URL", "").rstrip("/")


def _proxy_upload(task_id: str, filename: str, file_bytes: bytes,
                  content_type: str) -> dict:
    """POST the file to the backend so it lands on the backend's volume."""
    import httpx
    r = httpx.post(
        f"{_api_base()}/api/tasks/{task_id}/attachments",
        headers={"Authorization": f"Bearer {token_ctx.get()}"},
        files={"file": (filename, file_bytes, content_type)},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _proxy_fetch_bytes(attachment_id: str) -> bytes | None:
    """GET the attachment bytes from the backend's download route."""
    import httpx
    base, token = _api_base(), token_ctx.get()
    if not base or not token:
        return None
    try:
        r = httpx.get(
            f"{base}/api/attachments/{attachment_id}/download",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.warning(f"proxy fetch of attachment {attachment_id} failed: {e}")
        return None


@mcp.tool()
async def list_attachments(task_id: str, ctx: Context = None) -> list[dict]:
    """List all attachments for a task."""
    return services.list_attachments(task_id, actor=actor_ctx.get())

@mcp.tool()
async def upload_attachment(task_id: str, filename: str, content: str = "", content_base64: str = "", content_type: str = "application/octet-stream") -> dict:
    """Upload a file attachment to a task.

    For text (code, markdown, JSON, ...) pass it straight in `content` — no
    encoding needed. For binary, prefer uploading the file directly over HTTP
    (no base64) with your agent key, which is already in your env:
        curl -H "Authorization: Bearer $AGENTIRA_API_KEY" \\
             -F "file=@/path/to/file" "<API_BASE_URL>/api/tasks/<task_id>/attachments"
    `content_base64` is a last-resort fallback for binary over this tool.
    """
    import base64
    actor = actor_ctx.get()
    if content:
        file_bytes = content.encode("utf-8")
    elif content_base64:
        file_bytes = base64.b64decode(content_base64)
    else:
        return {"error": "Provide content (text) or content_base64 (binary)"}
    if _api_base():
        return _proxy_upload(task_id, filename, file_bytes, content_type)
    return services.add_attachment(
        task_id, filename, file_bytes, content_type,
        uploaded_by=actor, actor=actor,
    )

@mcp.tool()
async def download_attachment(attachment_id: str) -> dict:
    """Download an attachment by ID. Returns metadata and base64-encoded file content.

    Legacy tool. Prefer `read_attachment_text` — it returns text directly
    and a download/curl hint for binary, no base64 round-trip.
    """
    import base64
    from backend import attachments as _attachments
    result = services.get_attachment_bytes(
        attachment_id, actor=actor_ctx.get(),
    )
    if result:
        meta, file_bytes = result
        return {**meta, "content_base64": base64.b64encode(file_bytes).decode()}
    # Bytes aren't on this container's disk. Metadata lives in the shared DB;
    # fetch the bytes from the backend's volume over HTTP (AP-280).
    meta_fp = _attachments.get(attachment_id)
    if not meta_fp:
        return {"error": "Attachment not found"}
    file_bytes = _proxy_fetch_bytes(attachment_id)
    if file_bytes is not None:
        return {**meta_fp[0], "content_base64": base64.b64encode(file_bytes).decode()}
    # Can't proxy (no API base / token): fall back to the curl-hint shape.
    return _attachments.read_text(attachment_id) or {"error": "Attachment not found"}

# AP-152: project attachments + base64-free reads.

@mcp.tool()
async def list_project_attachments(project_id: str, ctx: Context = None) -> list[dict]:
    """List attachments uploaded against a project (briefs, designs, brand
    guides). Text files under 50KB include an `inline_text` field —
    everything else exposes a `download_url`. Pair with
    `read_attachment_text` for larger reads.
    """
    return services.list_project_attachments(
        project_id, actor=actor_ctx.get(),
    )


@mcp.tool()
async def read_attachment_text(attachment_id: str, ctx: Context = None) -> dict:
    """Read an attachment without base64.

    Text/* returns the file's content inline. Binary returns
    `download_url` + `api_key_env: "AGENTIRA_API_KEY"` + a curl hint —
    use `$AGENTIRA_API_KEY` from your env to fetch.
    """
    from backend import attachments as _attachments
    services.authorize_attachment_access(
        attachment_id, actor_ctx.get(), "read",
    )
    result = _attachments.read_text(attachment_id)
    if not result:
        return {"error": "Attachment not found"}
    # Text whose bytes aren't on this container's disk: read_text marks it
    # served_over_http. Pull the bytes from the backend's volume and inline
    # them if they decode as UTF-8 (AP-280); genuine binary keeps the hint.
    if "content" not in result and result.get("served_over_http"):
        data = _proxy_fetch_bytes(attachment_id)
        if data is not None:
            try:
                result["content"] = data.decode("utf-8")
                result.pop("served_over_http", None)
                result.pop("download_hint", None)
            except UnicodeDecodeError:
                pass
    return result

# ── Project Activity Tools ──────────────────────────────────────────────────────

@mcp.tool()
async def get_project_activity(project_id: str, limit: int = 50, ctx: Context = None) -> list[dict]:
    """Get recent activity across all tasks in a project. Use limit to control how many entries to return."""
    return services.get_project_activity(
        project_id, limit=limit, actor=actor_ctx.get(),
    )

# ── Metadata Tools ─────────────────────────────────────────────────────────────

@mcp.tool()
async def list_statuses() -> list[dict]:
    """List all available task statuses."""
    return services.list_statuses()

@mcp.tool()
async def list_roles() -> list[dict]:
    """List all user roles."""
    return services.list_roles()

@mcp.tool()
async def list_permissions() -> list[dict]:
    """List all available permissions."""
    return services.list_permissions()


# ── Forge run lifecycle ───────────────────────────────────────────────────────

@mcp.tool()
async def finish_run(
    run_id: str,
    outcome: str,
    summary: str = "",
    ctx: Context = None,
) -> dict:
    """Declare the semantic verdict of a Forge run you're working.

    Call this when you've finished (or stopped) work on a task that was
    dispatched to you. The Run.outcome field is what humans see in the
    UI as the primary "did this get done?" signal.

    Arguments:
      run_id:  the AGENTIRA_RUN_ID env var value passed to your process
               (also surfaced in your task prompt).
      outcome: one of:
        - "succeeded"   — the deliverable is in place
        - "blocked"     — couldn't proceed; needs human/external input
        - "needs_input" — paused with a specific question for the human
        - "failed"      — something is wrong; not recoverable mid-run
      summary: one paragraph describing what changed or what's blocking
               you. This is the line humans read first — be specific.

    The run's process status (running/completed/failed/cancelled) is
    tracked separately by the daemon. A run can be status=completed +
    outcome=blocked: the process exited cleanly but the agent declared
    it can't proceed.
    """
    from backend.forge import services as forge_services
    try:
        logger.info(f"Tool finish_run called: run={run_id} outcome={outcome}")
        res = forge_services.finish_run(run_id, outcome=outcome, summary=summary)
        if not res.get("ok"):
            logger.warning(f"Tool finish_run rejected: {res.get('error')}")
        return res
    except Exception as e:
        logger.error(f"Tool finish_run failed: {e}\n{traceback.format_exc()}")
        raise

@mcp.tool()
async def submit_review(run_id: str, approve: bool, note: str = "",
                        ctx: Context = None) -> dict:
    """Record your STRUCTURED review verdict for the task you're reviewing.

    This is how a reviewer approves or rejects — NOT a comment. The workflow
    engine merges a branch only when a typed APPROVE verdict from THIS review
    run exists; a free-text "REVIEW: APPROVE" comment does nothing. Call this
    once you've checked the PR diff against the DoD.

    Arguments:
      run_id:  your AGENTIRA_RUN_ID.
      approve: True to approve the work for merge, False to reject it.
      note:    optional one-line rationale (shown in the task feed).
    """
    from backend.forge import services as forge_services
    actor = actor_ctx.get()
    return forge_services.submit_review(run_id, approve=approve, actor=actor,
                                        note=note)

@mcp.tool()
async def get_my_involvement(ctx: Context = None) -> dict:
    """Summarize what THIS agent has been involved in across projects.

    Scoped to the calling agent — uses the AGENTIRA_AGENT_ID env var the
    daemon injects on every dispatch (so the answer is always "you", never
    another agent's data).

    Returns a project-level summary:
      {
        agent_id: "<id>",
        total_runs: N,
        total_input_tokens: N,
        total_output_tokens: N,
        total_cost_usd: float,
        projects: [{
          project_id, project_name,
          run_count, last_active,
          tasks_touched: [{task_id, task_title, last_run_at}]
        }],
      }

    Returns {error: "..."} if AGENTIRA_AGENT_ID isn't set (e.g. invoked
    outside a dispatched run).
    """
    import os
    agent_id = os.environ.get("AGENTIRA_AGENT_ID", "")
    if not agent_id:
        return {"error": "AGENTIRA_AGENT_ID env var not set; cannot scope involvement query."}
    from backend.forge import services as forge_services
    try:
        return forge_services.get_agent_involvement(agent_id)
    except Exception as e:
        logger.error(f"Tool get_my_involvement failed: {e}\n{traceback.format_exc()}")
        raise


# ── AP-121: Project repos ──────────────────────────────────────────────────────

@mcp.tool()
async def list_project_repos(project_id: str, ctx: Context = None) -> list[dict]:
    """List repos attached to a project (AP-121 multi-repo).

    Each returned dict: {id, project_id, name, repo_path, repo_url,
    default_branch, is_primary, created_at}. Use to discover which
    repos a project tracks before picking a `repo_name` on a task.
    """
    return services.list_project_repos(project_id, actor=actor_ctx.get())


# ── AP-125: Run artifacts ──────────────────────────────────────────────────────

@mcp.tool()
async def register_run_artifact(
    run_id: str,
    url: str,
    label: str = "",
    kind: str = "url",
    ctx: Context = None,
) -> dict:
    """Register a structured artifact produced by THIS run.

    The Run page surfaces artifacts as a "Here's what got built" panel,
    so the human reading the run sees the deliverable directly instead
    of scraping the chat transcript. Call this whenever you produce
    something the user is supposed to look at: a PR URL, a generated
    report file, a deployed preview URL, a build log, etc.

    Arguments:
      run_id: the AGENTIRA_RUN_ID env var the daemon injected on dispatch.
      url:    the artifact's address — http(s), file://, or a workspace-
              relative path. Required.
      label:  short human-readable name ("PR #42", "Audit report",
              "Deployed preview"). Optional but strongly recommended.
      kind:   one of "pr", "commit", "file", "url", "log", "report".
              Defaults to "url".

    Idempotent: re-registering the same (url, kind) refreshes the label.
    Capped at 50 artifacts per run.
    """
    from backend.forge import services as forge_services
    try:
        return forge_services.register_run_artifact(
            run_id=run_id, url=url, label=label, kind=kind,
            actor=actor_ctx.get(),
        )
    except Exception as exc:
        logger.error(f"register_run_artifact failed: {exc}\n{traceback.format_exc()}")
        raise


# ── AP-107: Run-investigation tools (read-only, prod-safe) ─────────────────────

@mcp.tool()
async def get_run(run_id: str, ctx: Context = None) -> dict:
    """Look up a specific Forge run by id.

    Returns the run's full state — status, outcome, agent verdict summary,
    timing, token + cost counters, workdir, diff stat, error message,
    initial prompt. Returns {error: "run_not_found"} for unknown ids.

    RBAC: you must be a member of the run's project (or hold the
    project.view_all wildcard). Read-only.
    """
    from backend.forge import services as forge_services
    actor = actor_ctx.get()
    try:
        return forge_services.get_run_detail(run_id, actor=actor)
    except PermissionError as e:
        return {"error": "forbidden", "detail": str(e)}


@mcp.tool()
async def get_run_events(run_id: str, limit: int = 100, offset: int = 0,
                         ctx: Context = None) -> dict:
    """Paginated event log for a run — the recorded tool calls, tool
    results, and assistant turns the runtime emitted.

    Each event: {role, tool_name, content, created_at}. `content` is
    capped per event; large outputs are suffixed with "…[truncated]".
    `limit` defaults to 100 and is capped at 500. RBAC same as get_run.
    """
    from backend.forge import services as forge_services
    actor = actor_ctx.get()
    try:
        return forge_services.list_run_events(
            run_id, actor=actor, limit=limit, offset=offset,
        )
    except PermissionError as e:
        return {"error": "forbidden", "detail": str(e)}


@mcp.tool()
async def get_run_diagnostics(run_id: str, ctx: Context = None) -> dict:
    """Post-mortem bundle for a run.

    Combines the agent-declared verdict (outcome + summary) with daemon-
    captured diagnostics (exit code, stderr tail, last events tail) so an
    investigator agent can answer "why did this run fail?" without
    touching the host machine. `status_vs_outcome` flags when the process
    result and the agent's verdict tell different stories (e.g. process
    failed but agent declared succeeded). RBAC same as get_run.
    """
    from backend.forge import services as forge_services
    actor = actor_ctx.get()
    try:
        return forge_services.get_run_diagnostics(run_id, actor=actor)
    except PermissionError as e:
        return {"error": "forbidden", "detail": str(e)}


# ── Transport: Streamable HTTP ─────────────────────────────────────────────────
# json_response=True → plain JSON body on POST (simpler, Bruno-compatible).
# Switch to False when enabling server-push notifications via GET /mcp.
session_manager = StreamableHTTPSessionManager(
    app=mcp._mcp_server,
    json_response=True,
    security_settings=None,
)


class _ASGIAdapter(Response):
    """Wrap an ASGI app so it can be returned from a Starlette route handler."""

    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send) -> None:
        await self.asgi_app(scope, receive, send)


async def mcp_handler(request: Request):
    """
    Single MCP endpoint — Streamable HTTP transport.

    POST /mcp  →  tool call / JSON-RPC request  →  JSON response
    GET  /mcp  →  server-initiated notifications  →  SSE stream (future)
    DELETE /mcp →  session cleanup
    """
    return _ASGIAdapter(session_manager.handle_request)


@contextlib.asynccontextmanager
async def lifespan(app_instance) -> AsyncIterator[None]:
    async with session_manager.run():
        logger.info("AgentIRA MCP Server ready — endpoint: POST /mcp (Streamable HTTP)")
        yield


# ── Starlette Application ──────────────────────────────────────────────────────

app = Starlette(
    debug=True,
    lifespan=lifespan,
    middleware=[Middleware(ASGILoggingMiddleware)],
    routes=[
        Route("/mcp", mcp_handler, methods=["GET", "POST", "DELETE"]),
    ],
)

if __name__ == "__main__":
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8000"))
    logger.info(f"Starting AgentIRA MCP Server on {host}:{port}")
    uvicorn.run(
        "backend.mcp_server:app",
        host=host,
        port=port,
        log_level="debug",
        reload=os.getenv("RAILWAY_ENVIRONMENT") is None,  # no reload in production
        reload_dirs=[os.path.join(BASE_DIR, "backend")] if os.getenv("RAILWAY_ENVIRONMENT") is None else None,
    )
