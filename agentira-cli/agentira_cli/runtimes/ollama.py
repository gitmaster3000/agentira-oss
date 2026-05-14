"""Ollama runtime — bare LLM gateway.

Per the runtime architecture (see `/Users/alifaraz/.claude/plans/...`):
Agentira owns the agent layer (persona, system_prompt, conversation history,
MCP). Ollama is a bare execution engine — it generates tokens and nothing
else. No bootstrap, no per-agent persona, no tool execution on the runtime
side. All of that comes from Agentira via the chat body.

Detection is by HTTP probe to `/api/tags`, not by binary on PATH. The
`ollama` CLI binary exists but it doesn't matter for our purposes — we
talk to the running daemon.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from .base import DetectedRuntime, Runtime

logger = logging.getLogger("agentira.runtime.ollama")

_DEFAULT_URL = "http://127.0.0.1:11434"


class OllamaRuntime(Runtime):
    provider = "ollama"
    default_binary = "ollama"
    env_path_override = "AGENTIRA_OLLAMA_PATH"
    capabilities = ("http_gateway",)
    # No static model catalog — models are whatever the user has pulled.
    # introspect() populates from /api/tags.
    models = ()

    @classmethod
    def detect(cls) -> DetectedRuntime | None:
        """Detect by HTTP probe, not by PATH lookup.

        Override base.detect() because Ollama is a service: the `ollama` CLI
        binary may exist while the daemon isn't running, and conversely the
        daemon may run on a remote host with no local binary at all.
        """
        url = os.environ.get("AGENTIRA_OLLAMA_URL", _DEFAULT_URL).rstrip("/")
        models, version = cls._probe(url)
        if models is None:
            # Daemon not reachable → don't register.
            return None
        return DetectedRuntime(
            provider=cls.provider,
            binary_path=url,  # virtual: the gateway URL stands in for binary
            version=version,
            capabilities=list(cls.capabilities),
            models=models,
            gateway_url=url,
            gateway_token="",  # Ollama has no auth by default
        )

    @classmethod
    def _probe(cls, url: str) -> tuple[list[str] | None, str | None]:
        """Hit /api/tags. Return (models, version) or (None, None) if down."""
        try:
            with urllib.request.urlopen(f"{url}/api/tags", timeout=3) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, TimeoutError, OSError) as exc:
            logger.debug("ollama probe failed at %s: %s", url, exc)
            return (None, None)
        except json.JSONDecodeError:
            return (None, None)

        models = []
        for m in data.get("models", []):
            mid = m.get("name") or m.get("model")
            if mid:
                # Prefix with `ollama/` so it's unambiguous downstream — same
                # convention OpenClaw uses when surfacing Ollama-routed models.
                models.append(f"ollama/{mid}")

        # Best-effort version: separate /api/version endpoint.
        version = None
        try:
            with urllib.request.urlopen(f"{url}/api/version", timeout=2) as resp:
                version = json.loads(resp.read()).get("version")
        except Exception:
            pass

        return (models, version)
