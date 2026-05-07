"""Build subprocess environment for spawned CLI agents.

Mirrors multica/server/internal/daemon/daemon.go:1121-1162.
"""

from __future__ import annotations

import os

_BLOCKED = {
    "AGENTIRA_DAEMON_API_KEY",
    "AGENTIRA_DAEMON_API_URL",
}


def build_env(
    *,
    api_url: str,
    api_key: str,
    task_id: str = "",
    agent_id: str = "",
    workspace_id: str = "",
    agent_name: str = "",
    extra: dict | None = None,
) -> dict:
    """Return env dict for a spawned CLI agent subprocess."""
    env = {k: v for k, v in os.environ.items() if k not in _BLOCKED}
    env.update({
        "AGENTIRA_SERVER_URL": api_url,
        "AGENTIRA_TOKEN": api_key,
        "AGENTIRA_TASK_ID": task_id,
        "AGENTIRA_AGENT_ID": agent_id,
        "AGENTIRA_WORKSPACE_ID": workspace_id,
        "AGENTIRA_AGENT_NAME": agent_name,
    })
    if extra:
        env.update(extra)
    return env
