from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from .base import Runtime

logger = logging.getLogger("agentira.runtime.claude")


class ClaudeRuntime(Runtime):
    provider = "claude"
    default_binary = "claude"
    env_path_override = "AGENTIRA_CLAUDE_PATH"
    capabilities = ("stream_json", "mcp_config", "resume", "compact")
    # Static list mixing claude-code's stable aliases (always-latest) with
    # a curated set of dated SKUs so users can pin an older generation if
    # they need reproducibility or a specific behavior. The CLI accepts
    # any of these directly — no API key, no introspection, no staleness
    # beyond what we ship here.
    #
    # Order: aliases first (most users want "latest"), then dated SKUs
    # newest-first. Users who want something not on this list can still
    # type a free-form value.
    models = (
        # Always-latest aliases — resolved by claude-code at call time.
        "sonnet",
        "opus",
        "haiku",
        # Pinned dated SKUs (newest first). 4.5+ only — older generations
        # aren't worth keeping in the dropdown; users who need them can
        # type the SKU as a free-form value.
        "claude-opus-4-5",
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
        # 1M-context variants (Sonnet only — Opus/Haiku stay at 200K).
        # Higher per-token cost; pick when the task genuinely needs the
        # extra window.
        "claude-sonnet-4-5[1m]",
        "sonnet[1m]",
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
        # Autonomous coding tasks routinely take 50-150 agentic turns
        # (read → edit → test → fix loops). 20 was far too low — runs hit
        # the cap mid-work and exited. 300 leaves ample headroom while
        # still capping a true runaway; the stale-run reconciler is the
        # backstop for genuinely stuck runs.
        max_turns: int = 300,
        system_prompt: str = "",
        mcp_config_path: str = "",
        mcp_strict: bool = False,
        resume_session_id: str = "",
        # AP-83 Path A: explicit tool allowlist on top of bypassPermissions.
        # bypassPermissions already skips permission prompts, but new MCP
        # servers and certain shell commands can still trip a prompt and
        # stall an overnight run. Enumerating the agent's expected tool
        # surface here makes the surface predictable and the run robust.
        # Empty tuple disables the flag.
        allowed_tools: tuple[str, ...] = (),
    ) -> list[str]:
        args = [
            "-p", prompt,
            "--output-format", "stream-json",
            # Note: do NOT pass --input-format stream-json. With both -p and
            # stream-json input set, claude-code waits for stream-json frames
            # on stdin and silently ignores -p, then exits 0 with no output
            # when stdin EOFs. We supply the prompt via -p; output parsing
            # is the only side that needs stream-json.
            "--verbose",
            "--permission-mode", "bypassPermissions",
            "--max-turns", str(max_turns),
        ]
        if mcp_strict:
            # Override mode: agent ONLY sees Agentira-configured servers.
            # Ignores the user's host ~/.claude.json MCP entries entirely.
            # Default is to merge host + Agentira so user-installed
            # integrations stay available.
            args.append("--strict-mcp-config")
        if model:
            args += ["--model", model]
        if system_prompt:
            args += ["--append-system-prompt", system_prompt]
        if mcp_config_path:
            args += ["--mcp-config", mcp_config_path]
        if resume_session_id:
            args += ["--resume", resume_session_id]
        if allowed_tools:
            # claude-code expects a single arg with space-separated tool
            # names. `mcp__<server>` wildcards every tool from that server;
            # `mcp__<server>__<tool>` pins one specific tool.
            args += ["--allowedTools", " ".join(allowed_tools)]
        return args

    @classmethod
    def parse_event(cls, line: str):
        return parse_stream_line(line)

    @classmethod
    def introspect(cls, binary_path: str) -> dict:
        """Resolve the model catalog without requiring an API key.

        claude-code authenticates via the user's logged-in session
        (Anthropic subscription), not a developer API key — and the
        /v1/models endpoint requires the latter. So we don't try to
        introspect Anthropic's catalog at all.

        Resolution order:
          1. AGENTIRA_CLAUDE_MODELS env var (comma-separated list) —
             power-user override. Lets users pin their preferred set
             without forking the package.
          2. cls.models tuple — base class falls back to this when
             introspect returns {}.

        The hardcoded tuple is kept current-generation-first so most
        users never need the override.
        """
        override = os.environ.get("AGENTIRA_CLAUDE_MODELS", "").strip()
        if not override:
            return {}
        ids = [m.strip() for m in override.split(",") if m.strip()]
        if not ids:
            return {}
        logger.info("Using AGENTIRA_CLAUDE_MODELS override: %d model(s)", len(ids))
        return {"models": ids}


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
    session_id: str = ""


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
        # claude-code emits subtype="success" even on rejected models or
        # API errors; the actual failure flag is `is_error`. When both
        # are present and is_error=true, treat the `result` text as the
        # error message (it's the human-readable explanation, e.g. "There's
        # an issue with the selected model …").
        subtype = msg.get("subtype", "")
        is_error = bool(msg.get("is_error"))
        success = (subtype == "success") and not is_error
        result_text = msg.get("result", "")
        explicit_error = msg.get("error", "")
        error = explicit_error or (result_text if is_error else "")
        if not success and not error:
            # A non-success result with no message — name the subtype so
            # the failure is legible (e.g. "error_max_turns": the agent
            # hit the turn cap) instead of falling through to a bare
            # "subprocess exited with code N".
            error = f"run ended early: {subtype or 'unknown'}"
        return ResultEvent(
            success=success,
            text="" if is_error else result_text,
            error=error,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    return None
