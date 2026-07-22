from __future__ import annotations

import json
import logging
import os

from .base import Runtime
from .claude import (
    ResultEvent,
    SessionEvent,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
)

logger = logging.getLogger("agentira.runtime.codex")


class CodexRuntime(Runtime):
    provider = "codex"
    default_binary = "codex"
    env_path_override = "AGENTIRA_CODEX_PATH"
    # CLI runtime like claude/grok — subprocess with JSONL stream, native
    # session resume (codex `exec resume <thread_id>`). No `mcp_config`: codex
    # takes MCP servers from ~/.codex/config.toml, not a per-turn flag.
    capabilities = ("stream_json", "resume")
    # Codex has no `codex models` introspection subcommand, so we ship a
    # curated static list (subscription auth resolves the real SKU server-side).
    # First entry is the default. Users can override via AGENTIRA_CODEX_MODELS
    # or type a free-form value.
    models = (
        "gpt-5-codex",
        "gpt-5",
        "o3",
        "o4-mini",
    )
    fallback_paths = (
        "~/.codex/bin/codex",
        "/usr/local/bin/codex",
        "/opt/homebrew/bin/codex",
        "~/.npm-global/bin/codex",
        "~/.volta/bin/codex",
    )

    @staticmethod
    def build_args(
        prompt: str,
        *,
        model: str = "",
        max_turns: int = 300,
        system_prompt: str = "",
        mcp_config_path: str = "",
        mcp_strict: bool = False,
        resume_session_id: str = "",
        allowed_tools: tuple[str, ...] = (),
    ) -> list[str]:
        # Codex has no `--system` flag (it reads AGENTS.md for standing
        # instructions), so the per-turn Profile system_prompt is prepended
        # to the prompt with a clear delimiter.
        final_prompt = (
            f"{system_prompt}\n\n---\n\n{prompt}" if system_prompt else prompt
        )
        # `--dangerously-bypass-approvals-and-sandbox` is the codex equivalent
        # of claude's `bypassPermissions` — required for an unattended run to
        # edit files and run commands without stalling on an approval prompt.
        # `--skip-git-repo-check` lets codex run in worktrees/temp dirs.
        flags = [
            "--json",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
        ]
        if model:
            flags += ["-m", model]
        if resume_session_id:
            # `codex exec resume <SESSION_ID> [PROMPT]` — resume takes the
            # thread_id emitted on `thread.started` plus the follow-up prompt.
            return ["exec", "resume", resume_session_id, *flags, final_prompt]
        return ["exec", *flags, final_prompt]

    @classmethod
    def parse_event(cls, line: str):
        """Parse one line of `codex exec --json` JSONL into a stream event.

        Codex event shapes (v0.145):
          {"type":"thread.started","thread_id":"<uuid>"}          -> SessionEvent
          {"type":"turn.started"}                                  -> ignored
          {"type":"item.started","item":{"type":"command_execution",...}}
                                                                   -> ToolUseEvent
          {"type":"item.completed","item":{"type":"agent_message","text":...}}
                                                                   -> TextEvent
          {"type":"item.completed","item":{"type":"command_execution",...}}
                                                                   -> ToolResultEvent
          {"type":"turn.completed","usage":{...}}                  -> ResultEvent(ok)
          {"type":"turn.failed","error":{"message":...}}           -> ResultEvent(err)
          {"type":"error","message":...}                           -> ResultEvent(err)
        """
        line = line.strip()
        if not line:
            return None
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return None

        mtype = msg.get("type", "")

        if mtype == "thread.started":
            tid = msg.get("thread_id", "")
            return SessionEvent(session_id=tid) if tid else None

        if mtype in ("item.started", "item.completed"):
            item = msg.get("item") or {}
            itype = item.get("type", "")
            if itype == "agent_message":
                # Emitted only on completion, with the full text present.
                if mtype == "item.completed":
                    return TextEvent(text=item.get("text", ""))
                return None
            if itype == "command_execution":
                if mtype == "item.started":
                    return ToolUseEvent(
                        tool_name="command_execution",
                        tool_input=item.get("command", ""),
                    )
                out = item.get("aggregated_output", "")
                code = item.get("exit_code")
                if code is not None:
                    out = f"{out}\n[exit {code}]" if out else f"[exit {code}]"
                return ToolResultEvent(tool_name="command_execution", output=out)
            return None

        if mtype == "turn.completed":
            usage = msg.get("usage") or {}
            return ResultEvent(
                success=True,
                input_tokens=usage.get("input_tokens", 0) or 0,
                output_tokens=usage.get("output_tokens", 0) or 0,
            )

        if mtype == "turn.failed":
            err = (msg.get("error") or {}).get("message", "") or "codex turn failed"
            return ResultEvent(success=False, error=err)

        if mtype == "error":
            return ResultEvent(
                success=False,
                error=msg.get("message", "") or "codex error",
            )

        return None

    @classmethod
    def introspect(cls, binary_path: str) -> dict:
        """Resolve models without an API key.

        Codex CLI authenticates via the user's ChatGPT subscription session,
        so there is no key-free catalog endpoint and no `codex models`
        subcommand. Honor an explicit override; otherwise fall back to
        cls.models (the base class does that when this returns {}).
        """
        override = os.environ.get("AGENTIRA_CODEX_MODELS", "").strip()
        if not override:
            return {}
        ids = [m.strip() for m in override.split(",") if m.strip()]
        if not ids:
            return {}
        logger.info("Using AGENTIRA_CODEX_MODELS override: %d model(s)", len(ids))
        return {"models": ids}
