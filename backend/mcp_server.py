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
from starlette.responses import Response, JSONResponse
from starlette.requests import Request
from starlette.routing import Route

from backend import services

# ── Global Actor Context ──────────────────────────────────────────────────────
# Set per-request by the auth middleware; read by tool handlers.
actor_ctx = contextvars.ContextVar("actor", default="system")

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
        is_authenticated = False

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                profile_dict = services.validate_api_key(token)
                if profile_dict:
                    actor = profile_dict.get("name", "unknown")
                    is_authenticated = True
                    logger.info(f"Resolved actor from token: {actor}")
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
async def get_project(project_id: str) -> dict:
    """Get project details."""
    return services.get_project(project_id)

@mcp.tool()
async def update_project(project_id: str, name: str = None, description: str = None) -> dict:
    """Update project metadata."""
    return services.update_project(project_id, name, description)

@mcp.tool()
async def delete_project(project_id: str) -> bool:
    """Delete a project."""
    return services.delete_project(project_id)

@mcp.tool()
async def add_project_member(project_id: str, profile_name: str, ctx: Context = None) -> dict:
    """Add a user to a project."""
    actor = actor_ctx.get()
    return services.add_project_member(project_id, profile_name, actor=actor)

@mcp.tool()
async def remove_project_member(project_id: str, profile_name: str) -> bool:
    """Remove a user from a project."""
    return services.remove_project_member(project_id, profile_name)

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
async def delete_epic(epic_id: str) -> bool:
    """Delete an epic."""
    return services.delete_epic(epic_id)

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
    ctx: Context = None,
) -> dict:
    """Create a new task in a project."""
    actor = actor_ctx.get()
    try:
        logger.info(f"Tool create_task called for project='{project_id}', title='{title}', actor='{actor}'")
        res = services.create_task(
            project_id, title, description, status, priority, assignee, tags, start_date=start_date, due_date=due_date, actor=actor
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
async def get_task(task_id: str) -> dict | None:
    """Get task details."""
    try:
        logger.info(f"Tool get_task called for task_id='{task_id}'")
        res = services.get_task(task_id)
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
    ctx: Context = None,
) -> dict:
    """Update task metadata. Use branch/pr_url to link git branch or PR. Use dod_items to set definition-of-done checklist (list of {text, checked}). Use start_date/due_date for roadmap planning. Use epic_id to attach to an epic (or empty string to detach)."""
    actor = actor_ctx.get()
    return services.update_task(task_id, title, description, priority, assignee, tags, start_date=start_date, due_date=due_date, dod_items=dod_items, branch=branch, pr_url=pr_url, epic_id=epic_id, actor=actor)

@mcp.tool()
async def move_task(task_id: str, status: str, ctx: Context = None) -> dict:
    """Change task status (e.g. move to 'in-progress')."""
    actor = actor_ctx.get()
    return services.move_task(task_id, status, actor=actor)

@mcp.tool()
async def delete_task(task_id: str) -> bool:
    """Delete a task."""
    return services.delete_task(task_id)

# ── Collaboration Tools ────────────────────────────────────────────────────────

@mcp.tool()
async def add_comment(task_id: str, comment: str, ctx: Context = None) -> dict:
    """Add a comment/activity log to a task."""
    actor = actor_ctx.get()
    return services.add_comment(task_id, comment, actor=actor)

@mcp.tool()
async def get_activity(task_id: str) -> list[dict]:
    """Get activity history and comments for a task."""
    return services.get_activity(task_id)

@mcp.tool()
async def get_task_activity(task_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
    """Get activity history for a task with pagination and structured diffs."""
    return services.get_activity(task_id, limit=limit, offset=offset)

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

@mcp.tool()
async def list_attachments(task_id: str) -> list[dict]:
    """List all attachments for a task."""
    return services.list_attachments(task_id)

@mcp.tool()
async def upload_attachment(task_id: str, filename: str, content_base64: str, content_type: str = "application/octet-stream") -> dict:
    """Upload a file attachment to a task. Encode file content as base64 and pass it as content_base64."""
    import base64
    actor = actor_ctx.get()
    file_bytes = base64.b64decode(content_base64)
    return services.add_attachment(task_id, filename, file_bytes, content_type, uploaded_by=actor)

@mcp.tool()
async def download_attachment(attachment_id: str) -> dict:
    """Download an attachment by ID. Returns metadata and base64-encoded file content."""
    import base64
    result = services.get_attachment_bytes(attachment_id)
    if not result:
        return {"error": "Attachment not found or file missing on disk"}
    meta, file_bytes = result
    return {**meta, "content_base64": base64.b64encode(file_bytes).decode()}

# ── Project Activity Tools ──────────────────────────────────────────────────────

@mcp.tool()
async def get_project_activity(project_id: str, limit: int = 50) -> list[dict]:
    """Get recent activity across all tasks in a project. Use limit to control how many entries to return."""
    return services.get_project_activity(project_id, limit=limit)

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
