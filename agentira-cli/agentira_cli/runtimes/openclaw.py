from __future__ import annotations

import json
import os
from pathlib import Path

from .base import Runtime

_DEFAULT_STATE_DIR = Path.home() / ".openclaw"
_DEFAULT_PORT = 18789


class OpenClawRuntime(Runtime):
    provider = "openclaw"
    default_binary = "openclaw"
    env_path_override = "AGENTIRA_OPENCLAW_PATH"
    version_args = ("--version",)
    capabilities = ("http_gateway",)

    @classmethod
    def introspect(cls, binary_path: str) -> dict:
        """Read openclaw.json to extract gateway URL, token, and available models."""
        state_dir = Path(os.environ.get("OPENCLAW_STATE_DIR", str(_DEFAULT_STATE_DIR)))
        config_path = state_dir / "openclaw.json"
        if not config_path.exists():
            return {}
        try:
            cfg = json.loads(config_path.read_text())
        except Exception:
            return {}

        gw = cfg.get("gateway", {})
        port = gw.get("port", _DEFAULT_PORT)
        bind = gw.get("bind", "loopback")
        host = "127.0.0.1" if bind in ("loopback", "localhost") else "0.0.0.0"
        gateway_url = f"http://{host}:{port}"

        auth = gw.get("auth", {})
        gateway_token = auth.get("token", "") if auth.get("mode") == "token" else ""

        # Gather all model ids from providers
        models: list[str] = []
        providers = cfg.get("models", {}).get("providers", {})
        for provider_cfg in providers.values():
            for m in provider_cfg.get("models", []):
                mid = m.get("id")
                if mid:
                    # Prefix with provider name so it's unambiguous
                    pname = provider_cfg.get("api") or list(providers.keys())[0]
                    models.append(f"{pname}/{mid}")

        # Default model
        default = (cfg.get("agents", {})
                     .get("defaults", {})
                     .get("model", {})
                     .get("primary", ""))
        if default and default not in models:
            models.insert(0, default)

        return {
            "gateway_url": gateway_url,
            "gateway_token": gateway_token,
            "models": models,
        }
