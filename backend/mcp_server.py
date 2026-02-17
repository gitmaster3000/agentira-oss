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

# ΓöÇΓöÇ Global Context ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
actor_ctx = contextvars.ContextVar("actor", default="system")

# ΓöÇΓöÇ Logging Setup ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("../mcp_server.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("mcp_server")
logger.setLevel(logging.DEBUG)

# ΓöÇΓöÇ Auth Implementation ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

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

# ΓöÇΓöÇ FastMCP Setup ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

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

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", []) if isinstance(k, bytes) and isinstance(v, bytes)}
        query_bytes = scope.get("query_string", b"")
        query = query_bytes.decode() if isinstance(query_bytes, bytes) else str(query_bytes)
        
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

# ΓöÇΓöÇ Tool Definitions ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

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

# ΓöÇΓöÇ Project Tools ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

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

# ΓöÇΓöÇ Task Tools ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

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

# ΓöÇΓöÇ Collaboration Tools ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

@mcp.tool()
async def add_comment(task_id: str, comment: str, ctx: Context = None) -> dict:
    """Add a comment/activity log to a task."""
    actor = actor_ctx.get()
    return services.add_comment(task_id, comment, actor=actor)

@mcp.tool()
async def get_activity(task_id: str) -> list[dict]:
    """Get activity history and comments for a task."""
    return services.get_activity(task_id)

# ΓöÇΓöÇ Metadata Tools ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

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

# ΓöÇΓöÇ Starlette App Lifecycle ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ


# Create the session manager for streamable-http transport
# This handles the "Legacy/IDE" connection style (POST /sse directly)
session_manager = StreamableHTTPSessionManager(
    app=mcp._mcp_server,
    json_response=True,
    security_settings=mcp.settings.transport_security
)

@contextlib.asynccontextmanager
async def combined_lifespan(app_instance) -> AsyncIterator[None]:
    """Unified lifespan for server (manages both transports)."""
    # Start the session manager (for IDE/HTTP)
    async with session_manager.run():
        logger.info("StreamableHTTP session manager started")
        # Start the FastMCP app (for Shim/SSE)
        async with sse_starlette_app.router.lifespan_context(sse_starlette_app):
            logger.info("FastMCP SSE sub-app lifespan started")
            yield

# ΓöÇΓöÇ Starlette App Configuration ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ



# 3. Unified /sse Endpoint
# We must handle GET, POST, and DELETE on /sse in a single route to avoid 405 Method Not Allowed
# because Starlette's Route matches path first.
sse_starlette_app = mcp.sse_app()

class ASGIResponder(Response):
    """
    A Starlette Response that wraps an ASGI application.
    This allows us to return an ASGI app (like sse_starlette_app or session_manager)
    from a route handler, and have Starlette await it properly.
    """
    def __init__(self, app_instance, status_code: int = 200, media_type: str | None = None):
         self.app_instance = app_instance
         self.status_code = status_code
         self.media_type = media_type

    async def __call__(self, scope, receive, send) -> None:
        await self.app_instance(scope, receive, send)

async def unified_sse_handler(request):
    """
    Handle all /sse traffic and route to Single Source of Truth (sse_starlette_app).
    - GET /sse: call sse_starlette_app directly (it handles GET /sse).
    - POST /sse: rewrite to /messages/ and call sse_starlette_app.
    - DELETE /sse: rewrite to /messages/ and call sse_starlette_app.
    """
    logger.debug(f"Unified SSE Handler hit: {request.method} {request.url.path}")
    
    if request.method == "GET":
        # Shim/Standard SSE Handshake
        return ASGIResponder(sse_starlette_app)
        
    elif request.method in ("POST", "DELETE"):
        # IDE/Legacy HTTP-like Interaction
        # Dispatch to StreamableHTTPSessionManager which allows POST init / sessionless-like behavior
        logger.debug("Dispatching POST/DELETE /sse to session_manager")
        return ASGIResponder(session_manager.handle_request)
        
    else:
        logger.warning(f"Method not allowed in unified handler: {request.method}")
        return JSONResponse({"error": "Method Not Allowed"}, status_code=405)

# 4. Create the Starlette App
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.middleware import Middleware

app = Starlette(
    debug=True,
    lifespan=combined_lifespan,
    middleware=[
        Middleware(ASGILoggingMiddleware),
    ],
    routes=[
        # 1. Intercept /sse for compatibility (IDE uses POST /sse, Std uses GET /sse)
        Route("/sse", unified_sse_handler, methods=["GET", "POST", "DELETE"]),
        
        # 2. Mount the Single Source of Truth app at root
        # This handles /messages/ (Standard Shim/Clients) and GET /sse (if hit directly)
        Mount("/", app=sse_starlette_app),
    ],
)

if __name__ == "__main__":
    logger.info("Starting Simplified AgentIRA MCP Server on 127.0.0.1:8000")
    # Enable reload=True for development to ensure code changes (like the _receive fix) apply immediately.
    # Note: When using reload, we must pass the app as an import string.
    uvicorn.run("backend.mcp_server:app", host="127.0.0.1", port=8000, log_level="debug", reload=True)
