from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .base import Runtime


class ClaudeRuntime(Runtime):
    provider = "claude"
    default_binary = "claude"
    env_path_override = "AGENTIRA_CLAUDE_PATH"
    capabilities = ("stream_json", "mcp_config", "resume")
    models = (
        "claude-sonnet-4-5",
        "claude-opus-4-5",
        "claude-haiku-4-5",
    )
    fallback_paths = (
        "~/.claude/local/claude",
        "~/.claude/local/node_modules/.bin/claude",
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
        "~/.npm-global/bin/claude",
        "~/.volta/bin/claude",
        "~/Library/Application Support/Claude/claude-code/*/claude.app/Contents/MacOS/claude",
    )

    @staticmethod
    def build_args(
        prompt: str,
        *,
        model: str = "",
        max_turns: int = 20,
        system_prompt: str = "",
        mcp_config_path: str = "",
        resume_session_id: str = "",
    ) -> list[str]:
        args = [
            "-p", prompt,
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--verbose",
            "--strict-mcp-config",
            "--permission-mode", "bypassPermissions",
            "--max-turns", str(max_turns),
        ]
        if model:
            args += ["--model", model]
        if system_prompt:
            args += ["--append-system-prompt", system_prompt]
        if mcp_config_path:
            args += ["--mcp-config", mcp_config_path]
        if resume_session_id:
            args += ["--resume", resume_session_id]
        return args

    @classmethod
    def parse_event(cls, line: str):
        return parse_stream_line(line)


# ── stream-json event types ───────────────────────────────────────────────

@dataclass
class TextEvent:
    text: str
    model: str = ""

@dataclass
class ToolUseEvent:
    tool_name: str
    tool_input: Any = None

@dataclass
class ToolResultEvent:
    tool_name: str
    output: str = ""

@dataclass
class SessionEvent:
    session_id: str

@dataclass
class UsageEvent:
    input_tokens: int = 0
    output_tokens: int = 0

@dataclass
class ResultEvent:
    success: bool
    text: str = ""
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def parse_stream_line(line: str):
    """Parse one line of Claude --output-format stream-json output.

    Returns one of the event dataclasses above, or None for unrecognised lines.
    Mirrors logic from multica/server/pkg/agent/claude.go:119-128.
    """
    line = line.strip()
    if not line:
        return None
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None

    msg_type = msg.get("type", "")

    if msg_type == "assistant":
        for block in msg.get("message", {}).get("content", []):
            btype = block.get("type", "")
            if btype == "text":
                return TextEvent(
                    text=block.get("text", ""),
                    model=msg.get("message", {}).get("model", ""),
                )
            if btype == "tool_use":
                return ToolUseEvent(
                    tool_name=block.get("name", ""),
                    tool_input=block.get("input"),
                )

    elif msg_type == "user":
        for block in msg.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                return ToolResultEvent(
                    tool_name=block.get("tool_use_id", ""),
                    output=str(block.get("content", "")),
                )

    elif msg_type == "system":
        sid = msg.get("session_id", "")
        if sid:
            return SessionEvent(session_id=sid)

    elif msg_type == "result":
        usage = msg.get("usage", {})
        return ResultEvent(
            success=msg.get("subtype") == "success",
            text=msg.get("result", ""),
            error=msg.get("error", ""),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    return None
