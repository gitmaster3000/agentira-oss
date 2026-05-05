"""MCP config tmpfile writer.

Mirrors multica/server/pkg/agent/claude.go:45-54.
"""

from __future__ import annotations

import json
import os
import tempfile


def write_mcp_config(config_json: str | dict) -> str:
    """Write MCP config to a temp file; caller must delete after use."""
    if isinstance(config_json, dict):
        data = json.dumps(config_json)
    else:
        data = config_json
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="agentira-mcp-", delete=False
    ) as f:
        f.write(data)
        return f.name


def remove_mcp_config(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
