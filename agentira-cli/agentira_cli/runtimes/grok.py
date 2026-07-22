from __future__ import annotations

import json
import logging
import os
import subprocess

from .base import Runtime, derive_session_handle as _derive_session_handle
from .claude import ResultEvent, TextEvent

logger = logging.getLogger("agentira.runtime.grok")


class GrokRuntime(Runtime):
    provider = "grok"
    default_binary = "grok"
    env_path_override = "AGENTIRA_GROK_PATH"
    capabilities = ("stream_json", "resume", "mcp_config")  # MCP is discovered from project config.
    # Fallback models if `grok models` introspection is unavailable.
    # Real list is fetched at runtime detect time by invoking the
    # `grok models` subcommand (headless). See introspect().
    models = (
        "grok-composer-2.5-fast",
        "grok-build",
    )
    fallback_paths = (
        "~/.grok/bin/grok",
        "~/.xai/bin/grok",
        "/usr/local/bin/grok",
        "/opt/homebrew/bin/grok",
        "~/.npm-global/bin/grok",
        "~/.volta/bin/grok",
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
        """Build arguments for Grok's headless CLI mode.

        Grok's option names and streaming format differ from Claude Code's:
        in particular, it accepts ``--single``/``--output-format
        streaming-json`` and rejects Claude's ``--verbose`` and
        ``stream-json`` values.
        """
        args = [
            "--single", prompt,
            "--output-format", "streaming-json",
            "--max-turns", str(max_turns),
        ]
        if model:
            args += ["--model", model]
        if system_prompt:
            args += ["--system-prompt-override", system_prompt]
        if resume_session_id:
            args += ["--resume", resume_session_id]
        if allowed_tools:
            for tool in allowed_tools:
                args += ["--allow", tool]
        return args

    @classmethod
    def parse_event(cls, line: str):
        """Map Grok ``streaming-json`` frames to Agentira stream events."""
        line = line.strip()
        if not line:
            return None
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return None

        msg_type = msg.get("type", "")
        if msg_type == "text":
            return TextEvent(text=msg.get("data", ""))
        if msg_type == "end":
            usage = msg.get("usage") or {}
            return ResultEvent(
                success=True,
                input_tokens=usage.get("input_tokens", 0) or 0,
                output_tokens=usage.get("output_tokens", 0) or 0,
                session_id=msg.get("sessionId", "") or "",
            )
        if msg_type == "error":
            usage = msg.get("usage") or {}
            return ResultEvent(
                success=False,
                error=msg.get("message", "") or "grok runtime error",
                input_tokens=usage.get("input_tokens", 0) or 0,
                output_tokens=usage.get("output_tokens", 0) or 0,
                session_id=msg.get("sessionId", "") or "",
            )
        return None

    @classmethod
    def introspect(cls, binary_path: str) -> dict:
        """Return live models by running `grok models` (or env override).

        This wires the terminal `/models` (exposed as `grok models` subcommand)
        into Agentira runtimes so that DetectedRuntime.models always reflects
        what the user's logged-in grok instance currently offers (composer2.5,
        grok-build, future additions, etc).

        Precedence:
          1. AGENTIRA_GROK_MODELS=... (comma list) — power user override.
          2. Output of `"<binary> models"` parsed for the Available models list.
          3. (caller falls back to) cls.models

        The fetch is cheap (local CLI, uses existing grok.com login) and runs
        on every detect (which the daemon does on start + periodic heartbeats).
        Results are "stored" in the DetectedRuntime that gets registered.
        """
        override = os.environ.get("AGENTIRA_GROK_MODELS", "").strip()
        if override:
            ids = [m.strip() for m in override.split(",") if m.strip()]
            if ids:
                logger.info("Using AGENTIRA_GROK_MODELS override: %d model(s)", len(ids))
                return {"models": ids}

        # Headless fetch using the exact same binary we will execute with.
        try:
            proc = subprocess.run(
                [binary_path, "models"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            text = (proc.stdout or "") + "\n" + (proc.stderr or "")
            ids = cls._parse_models_output(text)
            if ids:
                logger.info("Fetched %d live model(s) via `grok models` for runtime", len(ids))
                return {"models": ids}
            logger.debug("`grok models` produced no parseable models: %s", text[:200])
        except Exception as exc:
            logger.debug("grok models introspection failed for %s: %s", binary_path, exc)

        return {}

    @classmethod
    def _parse_models_output(cls, text: str) -> list[str]:
        """Parse the human output of `grok models`.

        Example:
          You are logged in with grok.com.

          Default model: grok-composer-2.5-fast

          Available models:
            * grok-composer-2.5-fast (default)
            - grok-build

        Returns models with the default (if announced) listed first.
        """
        if not text:
            return []
        models: list[str] = []
        default: str | None = None
        in_available = False

        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if "Default model:" in line:
                # "Default model: foo-bar"
                parts = line.split(":", 1)
                if len(parts) == 2:
                    cand = parts[1].strip().split()[0]
                    if cand:
                        default = cand
                continue
            if "Available models:" in line:
                in_available = True
                continue
            if not in_available:
                continue
            # list bullets: * foo (default)   or  - foo
            if line[0] in ("*", "-"):
                # take first token after the bullet and spaces
                rest = line[1:].strip()
                if rest:
                    mid = rest.split()[0]
                    if mid and mid not in models:
                        models.append(mid)

        # Promote default to front if we saw one and it is present.
        if default:
            if default in models:
                models.remove(default)
            models.insert(0, default)
        return models

    @classmethod
    def derive_session_handle(cls, *, agent_id: str, scope_key: str) -> str:
        # Support resume via session handle, similar to openclaw.
        return _derive_session_handle(agent_id=agent_id, scope_key=scope_key, prefix="grok")
