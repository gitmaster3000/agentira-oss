"""Daemon configuration — loads from env vars / .env file."""

from __future__ import annotations

import socket

from pydantic_settings import BaseSettings, SettingsConfigDict

from agentira_cli.state.paths import HOME


class DaemonConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTIRA_DAEMON_",
        env_file=str(HOME / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Server connection ────────────────────────────────────────────────
    # Defaults to a local dev stack. Point at your own Agentira instance with
    # AGENTIRA_DAEMON_API_URL (or `--api-url` on `daemon login`), e.g.
    # https://agentira.example.com.
    api_url: str = "http://127.0.0.1:8111"
    api_key: str = ""  # optional daemon auth token

    # ── Runtime host ─────────────────────────────────────────────────────
    device_name: str = socket.gethostname()
    heartbeat_interval: int = 30
    max_agent_turns: int = 20

    # ── Misc ─────────────────────────────────────────────────────────────
    dry_run: bool = False
    log_level: str = "INFO"
    # Check the backend for newer agentira-cli releases on daemon startup
    # (throttled). Set AGENTIRA_SKIP_UPDATE_CHECK=1 to disable.
    update_check_interval_hours: int = 24
