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
        if actor != "system":
            try:
                services.add_project_member(res["id"], actor, actor="system")
                logger.info(f"Added creator {actor} as member to project {res['id']}")
            except Exception as em:
                logger.warning(f"Failed to add creator as member: {em}")
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
    ctx: Context = None,
) -> dict:
    """Create a new task in a project."""
    actor = actor_ctx.get()
    try:
        logger.info(f"Tool create_task called for project='{project_id}', title='{title}', actor='{actor}'")
        res = services.create_task(
            project_id, title, description, status, priority, assignee, tags, actor=actor
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
    ctx: Context = None,
) -> dict:
    """Update task metadata."""
    actor = actor_ctx.get()
    return services.update_task(task_id, title, description, priority, assignee, tags, actor=actor)

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
    return services.mark_notification_read(notification_id)

# ── Attachment Tools ────────────────────────────────────────────────────────────

@mcp.tool()
async def list_attachments(task_id: str) -> list[dict]:
    """List all attachments for a task."""
    return services.list_attachments(task_id)

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
    logger.info("Starting AgentIRA MCP Server on 127.0.0.1:8000")
    uvicorn.run(
        "backend.mcp_server:app",
        host="127.0.0.1",
        port=8000,
        log_level="debug",
        reload=True,
    )
