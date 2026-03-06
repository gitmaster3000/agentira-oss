"""Daemon configuration — loads from env vars / .env file."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class DaemonConfig(BaseSettings):
    """Configuration for the Agentira daemon.

    All settings can be overridden via environment variables with
    AGENTIRA_DAEMON_ prefix or placed in an .env file.

    Example .env::

        AGENTIRA_DAEMON_API_URL=http://127.0.0.1:8111
        AGENTIRA_DAEMON_API_KEY=44f736d1c07a...
        AGENTIRA_DAEMON_POLL_INTERVAL=120
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTIRA_DAEMON_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Agentira connection ──────────────────────────────────────────────
    api_url: str = "http://127.0.0.1:8111"
    """Base URL of the Agentira REST API."""

    api_key: str = ""
    """Bot API key for authenticating with Agentira REST API."""

    bot_name: str = ""
    """Bot profile name. Auto-resolved from API key on startup if blank."""

    # ── Webhook receiver ─────────────────────────────────────────────────
    webhook_port: int = 0
    """Port for the inbound webhook receiver.  0 = disabled (poll-only mode)."""

    webhook_token: str = ""
    """Shared secret for X-Agentira-Token validation.  Empty = no auth (localhost-safe)."""

    # ── Polling ──────────────────────────────────────────────────────────
    poll_interval: int = 120
    """Seconds between task polls.  Default: 120 (2 minutes)."""

    # ── Agent execution ──────────────────────────────────────────────────
    zeroclaw_port: int = 42617
    """Port of the local ZeroClaw agent daemon."""

    max_agent_turns: int = 20
    """Maximum tool-call turns per task execution."""

    dry_run: bool = False
    """If True, log what would be done but don't call ZeroClaw."""

    # ── Logging ──────────────────────────────────────────────────────────
    log_level: str = "INFO"
    """Logging level: DEBUG, INFO, WARNING, ERROR."""
