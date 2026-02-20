import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from backend.mcp_server import ASGILoggingMiddleware

# ── ASGILoggingMiddleware Tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_logging_middleware_http():
    """Test that the middleware logs and passes through HTTP requests."""
    app = AsyncMock()
    middleware = ASGILoggingMiddleware(app)
    
    scope = {"type": "http", "method": "GET", "path": "/test"}
    receive = AsyncMock()
    send = AsyncMock()
    
    from unittest.mock import ANY
    await middleware(scope, receive, send)
    
    # Assert app was called
    app.assert_called_once_with(scope, receive, ANY)

@pytest.mark.asyncio
async def test_logging_middleware_non_http():
    """Test that non-HTTP scopes are ignored by the middleware."""
    app = AsyncMock()
    middleware = ASGILoggingMiddleware(app)
    
    scope = {"type": "websocket"}
    await middleware(scope, None, None)
    
    app.assert_called_once_with(scope, None, None)

# ── Tool Tests ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_project_tool():
    """Test the create_project tool call."""
    from backend.mcp_server import create_project, actor_ctx
    ctx = MagicMock()
    
    with patch("backend.services.create_project") as mock_service:
        token = actor_ctx.set("test-user")
        try:
            await create_project("New Project", "Desc", ctx=ctx)
            mock_service.assert_called_once_with("New Project", "Desc", actor="test-user")
        finally:
            actor_ctx.reset(token)

@pytest.mark.asyncio
async def test_list_tasks_tool():
    """Test the list_tasks tool call."""
    from backend.mcp_server import list_tasks, actor_ctx
    ctx = MagicMock()
    
    with patch("backend.services.list_tasks") as mock_service:
        token = actor_ctx.set("test-user")
        try:
            await list_tasks(project_id="123", status="todo", ctx=ctx)
            mock_service.assert_called_once_with("123", "todo", None, None, actor="test-user")
        finally:
            actor_ctx.reset(token)
