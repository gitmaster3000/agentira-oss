"""
AgentIRA MCP Server - Standard Protocol-Compliant Implementation.

This module provides a dual-transport MCP server (SSE and HTTP Stream) with 
authenticated access to AgentIRA's tools and resources.
"""

import logging
import sys
import traceback
import contextlib
from typing import Any, AsyncIterator
import uvicorn
import contextvars
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.auth.provider import TokenVerifier, AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, Response
from starlette.requests import Request
from starlette.routing import Route, Mount
from backend import services

# ── Global Context ──────────────────────────────────────────────────────
actor_ctx = contextvars.ContextVar("actor", default="system")

# ── Logging Setup ───────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("logs/mcp_server.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("mcp_server")
logger.setLevel(logging.DEBUG)

# ── Auth Implementation ──────────────────────────────────────────────────

class AgentIRAVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            profile = services.validate_api_key(token)
            if not profile:
                return None
            logger.info(f"Verified token for user: {profile.get('name', 'unknown')}")
            return AccessToken(
                token=token,
                client_id=profile.get("name", "anonymous"),
                scopes=["all"], 
            )
        except Exception as e:
            logger.warning(f"Token verification failed: {e}")
            return None

# ── FastMCP Setup ────────────────────────────────────────────────────────

auth_settings = AuthSettings(
    issuer_url="http://127.0.0.1:8000",
    resource_server_url="http://127.0.0.1:8000",
    required_scopes=["all"]
)

mcp = FastMCP(
    "AgentIRA",
    # Note: Auth handles in middleware
)

class ASGILoggingMiddleware:
    def __init__(self, app):
        self.app = app
        self.verifier = AgentIRAVerifier()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        method = scope.get("method")
        path = scope.get("path")
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        
        logger.info(f"REQ: {method} {path}")

        # Propagation: Extract actor from token if available
        actor = "system"
        auth_header = headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            profile = await self.verifier.verify_token(token)
            if profile:
                actor = profile.client_id
                logger.info(f"Resolved actor from token: {actor}")
            else:
                logger.warning("Token verification failed in middleware")
        else:
            logger.debug("No Authorization header found, defaulting to 'system'")
        
        token_reset = actor_ctx.set(actor)
        try:
            async def logging_send(message):
                if message["type"] == "http.response.start":
                    logger.info(f"RES: {message['status']} (Handled {method} {path})")
                await send(message)
            await self.app(scope, receive, logging_send)
        except Exception:
            logger.error(f"ERR: {method} {path} failed:\n{traceback.format_exc()}")
            raise
        finally:
            actor_ctx.reset(token_reset)

# ── Tool Definitions ─────────────────────────────────────────────────────

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
         return {'error': 'Invalid credentials'}
    
    with services._session() as db:
        p = db.query(services.Profile).filter(services.Profile.name == name).first()
        res = services._profile_to_dict(p)
        res["api_key"] = p.api_key
        return res

# ── Project Tools ────────────────────────────────────────────────────────

@mcp.tool()
async def create_project(name: str, description: str = "", ctx: Context = None) -> dict:
    """Create a new project."""
    actor = actor_ctx.get()
    try:
        logger.info(f"Tool create_project called with name='{name}', actor='{actor}'")
        res = services.create_project(name, description, actor=actor)
        
        # Automatically add the creator as a member so they can create tasks
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
        raise e

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

# ── Task Tools ───────────────────────────────────────────────────────────

@mcp.tool()
async def create_task(
    project_id: str,
    title: str,
    description: str = "",
    status: str = "backlog",
    priority: str = "medium",
    assignee: str = "",
    tags: list[str] = None,
    ctx: Context = None
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
        raise e

@mcp.tool()
async def list_tasks(
    project_id: str = None,
    status: str = None,
    assignee: str = None,
    priority: str = None,
    ctx: Context = None
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
        raise e

@mcp.tool()
async def update_task(
    task_id: str,
    title: str = None,
    description: str = None,
    priority: str = None,
    assignee: str = None,
    tags: list[str] = None,
    ctx: Context = None
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

# ── Collaboration Tools ───────────────────────────────────────────────────

@mcp.tool()
async def add_comment(task_id: str, comment: str, ctx: Context = None) -> dict:
    """Add a comment/activity log to a task."""
    actor = actor_ctx.get()
    return services.add_comment(task_id, comment, actor=actor)

@mcp.tool()
async def get_activity(task_id: str) -> list[dict]:
    """Get activity history and comments for a task."""
    return services.get_activity(task_id)

# ── Metadata Tools ────────────────────────────────────────────────────────

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

# ── Starlette App Lifecycle ──────────────────────────────────────────────

@contextlib.asynccontextmanager
async def combined_lifespan(app_instance) -> AsyncIterator[None]:
    """Unified lifespan for the MCP server."""
    logger.info("AgentIRA MCP Server lifespan starting")
    
    # Trigger sub-app lifespan if it has one
    async with mcp_app.router.lifespan_context(mcp_app):
        logger.info("AgentIRA MCP Sub-app lifespan started")
        yield
        logger.info("AgentIRA MCP Sub-app lifespan ending")
    
    logger.info("AgentIRA MCP Server lifespan ending")

# ── Starlette App Configuration ──────────────────────────────────────────

# Create the FastMCP SSE application
# This app handles both GET (SSE) and POST (JSON-RPC) correctly in a single context.
mcp_app = mcp.sse_app()

# ── Create the Starlette App ──────────────────────────────────────────
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.middleware import Middleware

root_app = Starlette(
    debug=True,
    lifespan=combined_lifespan,
    middleware=[
        Middleware(ASGILoggingMiddleware),
    ],
    routes=[
        # Mount the MCP SSE application at /
        # GET /sse -> The EventStream (defined in sub-app)
        # POST /messages -> The JSON-RPC endpoint (defined in sub-app)
        Mount("/", app=mcp_app),
    ],
)

# Alias 'app' for uvicorn
app = root_app

if __name__ == "__main__":
    logger.info("Starting Consolidated AgentIRA MCP Server on 127.0.0.1:8000")
    import uvicorn
    # Use reload=True with reload_dirs specifically for the backend folder.
    uvicorn.run("backend.mcp_server:app", host="127.0.0.1", port=8000, log_level="debug", reload=True, reload_dirs=["backend"])
