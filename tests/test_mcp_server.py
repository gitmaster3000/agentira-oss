import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from backend.mcp_server import AgentIRAVerifier, ASGILoggingMiddleware, SSEHandler

# ── AgentIRAVerifier Tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verifier_success():
    """Test successful token verification."""
    mock_profile = {"id": 1, "name": "test-user", "api_key": "valid-key"}
    with patch("backend.services.validate_api_key", return_value=mock_profile):
        verifier = AgentIRAVerifier()
        result = await verifier.verify_token("valid-key")
        
        assert result is not None
        assert result.token == "valid-key"
        assert result.client_id == "test-user"

@pytest.mark.asyncio
async def test_verifier_failure():
    """Test token verification failure."""
    with patch("backend.services.validate_api_key", side_effect=Exception("Invalid")):
        verifier = AgentIRAVerifier()
        result = await verifier.verify_token("invalid-key")
        assert result is None

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

# ── SSEHandler Tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sse_handler_get_method_not_allowed():
    """Test that GET requests to SSEHandler return 405."""
    handler = SSEHandler()
    scope = {"type": "http", "method": "GET"}
    receive = AsyncMock()
    send = AsyncMock()
    
    await handler(scope, receive, send)
    
    # Check that a 405 response was started
    # Note: JSONResponse might add more headers/formatting, using ANY for flexibility
    from unittest.mock import ANY
    send.assert_any_call({
        "type": "http.response.start",
        "status": 405,
        "headers": ANY
    })

@pytest.mark.asyncio
async def test_sse_handler_post_delegation():
    """Test that POST requests are delegated to the session manager."""
    handler = SSEHandler()
    scope = {"type": "http", "method": "POST"}
    receive = AsyncMock()
    send = AsyncMock()
    
    with patch("backend.mcp_server.session_manager.handle_request", new_callable=AsyncMock) as mock_handle:
        await handler(scope, receive, send)
        mock_handle.assert_called_once_with(scope, receive, send)

# ── New Tool Tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_project_tool():
    """Test the create_project tool call."""
    from backend.mcp_server import create_project
    ctx = MagicMock()
    ctx.client_id = "test-user"
    
    with patch("backend.services.create_project") as mock_service:
        await create_project("New Project", "Desc", ctx=ctx)
        mock_service.assert_called_once_with("New Project", "Desc", actor="test-user")

@pytest.mark.asyncio
async def test_list_tasks_tool():
    """Test the list_tasks tool call."""
    from backend.mcp_server import list_tasks
    ctx = MagicMock()
    ctx.client_id = "test-user"
    
    with patch("backend.services.list_tasks") as mock_service:
        await list_tasks(project_id="123", status="todo", ctx=ctx)
        mock_service.assert_called_once_with("123", "todo", None, None, actor="test-user")
