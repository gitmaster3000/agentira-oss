"""AP-83 Path A — explicit --allowedTools allowlist for claude-code.

bypassPermissions alone leaves a window: new MCP servers introduced
mid-session, and a few shell paths, can still trip a permission prompt
and stall an overnight autonomous run. Emitting --allowedTools enumerates
the agent's expected tool surface so the run never asks.
"""

from __future__ import annotations

import json

from agentira_cli.runtimes.claude import ClaudeRuntime
from agentira_cli.daemon.executor import _derive_allowed_tools


# ── build_args ─────────────────────────────────────────────────────────

def test_build_args_emits_allowed_tools_when_provided():
    args = ClaudeRuntime.build_args(
        "go", allowed_tools=("Read", "Edit", "mcp__agentira"),
    )
    i = args.index("--allowedTools")
    # claude-code expects a single space-separated value, not multiple args.
    assert args[i + 1] == "Read Edit mcp__agentira"


def test_build_args_omits_allowed_tools_by_default():
    args = ClaudeRuntime.build_args("go")
    assert "--allowedTools" not in args


def test_build_args_omits_allowed_tools_when_empty():
    args = ClaudeRuntime.build_args("go", allowed_tools=())
    assert "--allowedTools" not in args


# ── _derive_allowed_tools ──────────────────────────────────────────────

def test_derive_includes_claude_builtins():
    out = _derive_allowed_tools(None, "claude")
    # The stable claude-code builtins must be in the allowlist.
    for tool in ("Read", "Edit", "Write", "Bash", "Grep", "Glob"):
        assert tool in out


def test_derive_adds_mcp_server_wildcards():
    cfg = json.dumps({"mcpServers": {"agentira": {"transport": "http"},
                                     "memory": {"transport": "http"},
                                     "agentira-project": {"transport": "http"}}})
    out = _derive_allowed_tools(cfg, "claude")
    assert "mcp__agentira" in out
    assert "mcp__memory" in out
    assert "mcp__agentira-project" in out


def test_derive_returns_empty_for_non_claude_provider():
    """Other runtimes don't speak --allowedTools today — defer to their
    own permission models rather than passing a flag they don't use."""
    cfg = json.dumps({"mcpServers": {"agentira": {}}})
    assert _derive_allowed_tools(cfg, "openclaw") == ()
    assert _derive_allowed_tools(cfg, "codex") == ()


def test_derive_tolerates_malformed_mcp_config():
    """Builtins still get through even if the MCP config blob can't be parsed."""
    out = _derive_allowed_tools("{not json", "claude")
    assert "Read" in out
    assert not any(t.startswith("mcp__") for t in out)


def test_derive_handles_missing_mcp_servers_key():
    out = _derive_allowed_tools(json.dumps({}), "claude")
    assert "Read" in out
    assert not any(t.startswith("mcp__") for t in out)
