"""Daemon configuration — loads from env vars / .env file."""

from __future__ import annotations

import socket

from pydantic_settings import BaseSettings, SettingsConfigDict


class DaemonConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTIRA_DAEMON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Server connection ────────────────────────────────────────────────
    # Defaults to the hosted Agentira backend. Override with
    # AGENTIRA_DAEMON_API_URL (or `--api-url` on `daemon login`) for a local
    # dev stack, e.g. http://127.0.0.1:8111.
    api_url: str = "https://flowty-api-production.up.railway.app"
    api_key: str = ""  # optional daemon auth token

    # ── Runtime host ─────────────────────────────────────────────────────
    device_name: str = socket.gethostname()
    heartbeat_interval: int = 30
    max_agent_turns: int = 20

    # ── Misc ─────────────────────────────────────────────────────────────
    dry_run: bool = False
    log_level: str = "INFO"
