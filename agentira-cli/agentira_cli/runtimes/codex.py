from __future__ import annotations

import json
import logging
import os
from pathlib import Path

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
    # Codex has no `codex models` subcommand, but the CLI fetches the
    # account's model catalog (the same list the interactive `/model` picker
    # shows) from chatgpt.com using the logged-in session and caches it to
    # `$CODEX_HOME/models_cache.json`. introspect() reads that cache for live,
    # per-account discovery.
    #
    # No static fallback list: a hardcoded set goes stale and would offer
    # models the account can't select. When discovery finds nothing (fresh
    # install codex has never run, cache unreadable), we advertise an empty
    # list so the UI prompts "type a model" instead of showing dead options.
    # Users can still pin via AGENTIRA_CODEX_MODELS or type a free-form value.
    models = ()
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
        """Resolve the live model list without an API key.

        Precedence:
          1. AGENTIRA_CODEX_MODELS=... (comma list) — power-user override.
          2. `$CODEX_HOME/models_cache.json` — the account's catalog the codex
             CLI fetched from chatgpt.com under the logged-in session (same
             list `/model` shows). Refreshed by codex itself; we just read it.
          3. (caller falls back to) cls.models.

        Mirrors grok's live discovery, adapted to codex's cache-file shape
        (codex has no `codex models` subcommand to shell out to).
        """
        override = os.environ.get("AGENTIRA_CODEX_MODELS", "").strip()
        if override:
            ids = [m.strip() for m in override.split(",") if m.strip()]
            if ids:
                logger.info(
                    "codex models source=AGENTIRA_CODEX_MODELS override: %d model(s) %s",
                    len(ids), ids,
                )
                return {"models": ids}

        cache_path = cls._codex_home() / "models_cache.json"
        ids = cls._read_cached_models(cache_path)
        if ids:
            logger.info(
                "codex models source=%s: %d model(s) %s", cache_path, len(ids), ids,
            )
            return {"models": ids}
        # No override, no usable cache — advertise nothing (UI prompts for a
        # free-form model). _read_cached_models already logged *why* the cache
        # was unusable (absent vs corrupt vs malformed).
        logger.info(
            "codex models source=none: live discovery found no models "
            "(cache %s); UI will prompt for a free-form model", cache_path,
        )
        return {}

    @staticmethod
    def _codex_home() -> Path:
        home = os.environ.get("CODEX_HOME", "").strip()
        return Path(home) if home else Path.home() / ".codex"

    @staticmethod
    def _read_cached_models(path: Path) -> list[str]:
        """Parse listable model slugs from `models_cache.json`, priority order.

        Entry shape: {"slug": "...", "visibility": "list"|"hide", "priority": N}.
        Only `visibility == "list"` models are user-selectable (hidden internal
        SKUs like codex-auto-review are dropped); ties/absent priority sink last.

        Logs the failure mode so a broken discovery is diagnosable from the
        daemon log alone: absent cache (debug — normal on a fresh install) vs
        unreadable file / malformed JSON / bad schema (warning — real breakage).
        """
        if not path.exists():
            logger.debug(
                "codex models_cache.json absent at %s — codex CLI has not run "
                "yet (no live models to advertise)", path,
            )
            return []
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            logger.warning(
                "codex model discovery failed: %s unreadable/not JSON (%s) — "
                "advertising no models", path, exc,
            )
            return []
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            logger.warning(
                "codex model discovery failed: %s has no `models` list "
                "(schema drift?) — advertising no models", path,
            )
            return []
        listable = [
            m for m in models
            if isinstance(m, dict) and m.get("slug") and m.get("visibility") == "list"
        ]
        listable.sort(key=lambda m: m.get("priority", 1_000_000))
        out: list[str] = []
        for m in listable:
            slug = m["slug"]
            if slug not in out:
                out.append(slug)
        if not out:
            logger.warning(
                "codex model discovery: %s parsed but no visibility=list models "
                "(%d entries total) — advertising no models", path, len(models),
            )
        return out
