from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import ClassVar


# ── Capability flags ──────────────────────────────────────────────────────
#
# String constants the registered runtime advertises via `capabilities`. The
# backend reads these (in `services.send_runtime_message` and friends) to
# decide whether to pass `resume_session_id`, prepend history, etc. Keep the
# constants and the legacy literal strings (claude already ships "resume" /
# "stream_json" / "mcp_config") in sync — `Capability.RESUME == "resume"`.
#
# This is part of the ADR-009 Runtime Adapter contract: every adapter
# declares what it can do natively; the upper layers backfill the rest
# (history-replay for runtimes without `RESUME`, etc.).
class Capability:
    RESUME = "resume"                # provider has a native session/thread handle
    STREAM_EVENTS = "stream_events"  # provider pushes live tokens / tool events
    STOP = "stop"                    # provider exposes a wire-level cancel
    PAUSE = "pause"                  # provider supports clean-terminate + resume
    TOOLS = "tools"                  # provider hosts tool execution itself
    MCP = "mcp"                      # provider accepts MCP server config

    # Legacy wire-shape labels in use today — semantic equivalents above.
    STREAM_JSON = "stream_json"      # CLI runtime streams stream-json over stdout
    HTTP_GATEWAY = "http_gateway"    # gateway runtime (HTTP/WebSocket)
    MCP_CONFIG = "mcp_config"        # claude's --mcp-config

    @classmethod
    def all(cls) -> set[str]:
        return {v for k, v in vars(cls).items()
                if not k.startswith("_") and isinstance(v, str)}


# Scope keys per ADR 008 are "task:<id>", "chat:project:<id>", "chat:default".
# We sanitize before mixing into a session handle so it works as a filesystem
# fragment, a URL segment, or an OpenClaw sessionKey. Keep it printable and
# stable: alnum, `:`, `-`, `_`, `.`.
_SCOPE_SANITIZE = re.compile(r"[^A-Za-z0-9._:\-]+")


def derive_session_handle(*, agent_id: str, scope_key: str,
                          prefix: str = "agentira") -> str:
    """Deterministic per-(agent, scope) handle.

    Used by adapters whose providers expose a server-side thread/session
    keyed by a string (OpenClaw's `sessionKey`, etc.). Stable input ->
    stable handle, so the same scope always resumes the same thread.

    Format: `<prefix>:<agent_id[:8]>:<sanitized_scope>` — short enough to
    be readable in logs, long enough to avoid collisions.
    """
    if not agent_id or not scope_key:
        return ""
    a = agent_id[:8]
    scope = _SCOPE_SANITIZE.sub("_", scope_key)
    return f"{prefix}:{a}:{scope}"


@dataclass
class DetectedRuntime:
    provider: str
    binary_path: str
    version: str | None
    capabilities: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    gateway_url: str = ""
    gateway_token: str = ""


class Runtime:
    """Base class for a CLI runtime provider.

    Subclasses set class attrs and override build_args/parse_event in later phases.
    """

    provider: ClassVar[str] = ""
    default_binary: ClassVar[str] = ""
    env_path_override: ClassVar[str] = ""  # e.g. "AGENTIRA_CLAUDE_PATH"
    version_args: ClassVar[tuple[str, ...]] = ("--version",)
    capabilities: ClassVar[tuple[str, ...]] = ()
    fallback_paths: ClassVar[tuple[str, ...]] = ()  # absolute paths to probe if not on PATH
    models: ClassVar[tuple[str, ...]] = ()  # supported model identifiers (first = default)

    @classmethod
    def build_args(cls, prompt: str, **kwargs) -> list[str]:
        raise NotImplementedError

    @classmethod
    def parse_event(cls, line: str):
        return None

    @classmethod
    def introspect(cls, binary_path: str) -> dict:
        """Optional: query a running runtime for live config (gateway URL, token, models).
        Override in gateway-type runtimes. Returns {} by default."""
        return {}

    # ── ADR 009 — Runtime Adapter contract ──────────────────────────────
    #
    # An adapter maps a deterministic per-(agent, scope_key) handle to its
    # native continuity primitive (claude session id by cwd, OpenClaw
    # sessionKey, etc.). Default returns "" — the runtime has no native
    # resume and the backend will fall back to history-replay
    # (`_prepend_history_for_prompt`). Adapters with `Capability.RESUME`
    # MUST override and return a stable handle.

    @classmethod
    def derive_session_handle(cls, *, agent_id: str, scope_key: str) -> str:
        """Provider-native handle for `(agent, scope)`, or "" when not
        applicable. Stable across calls so the same scope resumes the same
        provider-side thread/session.

        claude returns "" — it keys `--resume` by *cwd* (the per-(agent,
        task) worktree from ADR 009 / A2), not by an Agentira-derived
        string. OpenClaw and similar gateway runtimes override to return
        a sanitized `agentira:<agent>:<scope>` handle.
        """
        return ""

    @classmethod
    def clear_handle(cls, *, agent_id: str, scope_key: str) -> None:
        """Provider-side `/clear` (ADR 008). Default no-op.

        - claude: opaque session files in `~/.claude` — no provider call
          needed; the backend dropping `runtime_session_id` is enough.
        - openclaw: TBD — call delete-thread by sessionKey when the API
          exposes one, else rotate a generation suffix on the handle.
        - ollama / bare LLM: no thread to clear.
        """
        return None

    @classmethod
    def detect(cls) -> DetectedRuntime | None:
        override = os.environ.get(cls.env_path_override)
        if override:
            path = shutil.which(override) or (override if os.path.isfile(override) and os.access(override, os.X_OK) else None)
        else:
            path = shutil.which(cls.default_binary)
            if not path:
                for fp in cls.fallback_paths:
                    expanded = os.path.expanduser(fp)
                    matches = sorted(glob.glob(expanded), reverse=True) if any(c in expanded for c in "*?[") else [expanded]
                    for m in matches:
                        if os.path.isfile(m) and os.access(m, os.X_OK):
                            path = m
                            break
                    if path:
                        break
        if not path:
            return None
        extra = cls.introspect(path)
        return DetectedRuntime(
            provider=cls.provider,
            binary_path=path,
            version=cls._read_version(path),
            capabilities=list(cls.capabilities),
            models=extra.get("models") or list(cls.models),
            gateway_url=extra.get("gateway_url", ""),
            gateway_token=extra.get("gateway_token", ""),
        )

    @classmethod
    def _read_version(cls, path: str) -> str | None:
        try:
            out = subprocess.run(
                [path, *cls.version_args],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        text = (out.stdout or out.stderr).strip()
        return text.splitlines()[0] if text else None
