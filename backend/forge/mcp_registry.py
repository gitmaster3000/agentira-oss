"""Global MCP server registry — definitions of which MCP servers are
available to agents in this deployment.

Lives as a Python dict for now. When this gains weight (per-deployment
custom servers, secret rotation, multi-tenant), promote to a database
table — same `name -> definition` shape, no caller changes.

Each entry describes how the daemon should spawn or connect to an MCP
server. The `auto` flag marks servers that get injected on every run
regardless of agent.mcp_servers (e.g. the agentira MCP for finish_run).

Frontend pickers should hide `auto` servers — users can't toggle them.
"""

from __future__ import annotations

import os
from typing import Any


# Registry. The auth_env_var field names the env var the daemon must
# populate for the server to authenticate; how that value is resolved
# is a daemon-side concern (build_mcp_config provides documented values
# like MEMORY_FILE_PATH, the daemon fills others from its own config).
REGISTRY: dict[str, dict[str, Any]] = {
    "agentira": {
        "transport": "http",
        # NOTE: this URL is baked into the agent's --mcp-config and dialed
        # by claude-code running on the daemon host. It must be reachable
        # from the host, NOT from inside the backend container. Default to
        # localhost:8000 (the dev compose maps mcp:8000 → host 8000). Prod
        # deployments override via AGENTIRA_MCP_URL (e.g. public URL).
        "url": os.environ.get("AGENTIRA_MCP_URL", "http://localhost:8000/mcp"),
        "auth_env_var": "AGENTIRA_API_KEY",
        "description": "Read/write tasks, projects, comments. Required for finish_run.",
        "auto": True,   # always injected; users can't deselect
    },
    "memory": {
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-memory"],
        "auth_env_var": None,
        "description": "Per-(agent, project) knowledge graph for what the agent learns over time.",
        # Auto-injected with a per-(agent, project) MEMORY_FILE_PATH
        # set by build_mcp_config — kept out of the user-facing picker.
        "auto": True,
    },
    "agentira-project": {
        "transport": "stdio",
        "command": ["python3", "-m", "agentira_cli.mcp.agentira_project"],
        "auth_env_var": None,
        "description": "Read project files, search code, read conventions — pull context on demand.",
        # Auto-injected ONLY when the agent is bound to a project (has
        # AGENTIRA_REPO_PATH). build_mcp_config conditionally includes it.
        "auto": False,
        "auto_when_project": True,
    },
}


def list_servers(*, include_auto: bool = True) -> list[dict[str, Any]]:
    """Return the registry as a list. Default includes auto servers; the
    UI picker should pass include_auto=False to hide them."""
    out = []
    for name, defn in REGISTRY.items():
        if not include_auto and defn.get("auto"):
            continue
        out.append({
            "name": name,
            "transport": defn["transport"],
            "description": defn.get("description", ""),
            "auto": defn.get("auto", False),
        })
    return out


def get_server(name: str) -> dict[str, Any] | None:
    return REGISTRY.get(name)


def build_mcp_config(*, agent_mcp_servers: list[str] | None,
                     agent_id: str, project_id: str | None,
                     agent_api_key: str | None = None,
                     mcp_config_override: str | dict | None = None,
                     disabled_servers: list[str] | None = None,
                     agent_home_path: str | None = None,
                     repo_path: str | None = None,
                     memory_root: str = "~/.agentira/memory") -> dict[str, Any]:
    """Resolve which MCP servers a run gets and produce the JSON config the
    daemon will write to a tmpfile and pass via --mcp-config.

    Resolution order:
      1. All `auto` servers from REGISTRY (always included).
      2. Plus the names in `agent_mcp_servers` that exist in REGISTRY and
         aren't auto (auto servers can't be double-added or skipped).

    Special-cases:
      - The `memory` server's MEMORY_FILE_PATH is scoped per
        (agent_id, project_id) so the same agent on different projects
        gets different memory.
      - Unknown server names in agent_mcp_servers are silently dropped —
        the registry is the source of truth and we don't fail a dispatch
        on a stale agent config.

    Returns the dict shape claude/codex expect for --mcp-config:
      {"mcpServers": {name: {<server-definition>}, ...}}
    """
    selected = set()
    # auto servers always
    for name, defn in REGISTRY.items():
        if defn.get("auto"):
            selected.add(name)
        # Conditionally auto-include when agent has a project binding.
        if defn.get("auto_when_project") and project_id:
            selected.add(name)
    # agent's choices, filtered against the registry
    for name in (agent_mcp_servers or []):
        if name in REGISTRY and not REGISTRY[name].get("auto"):
            selected.add(name)

    mcp_servers: dict[str, Any] = {}
    for name in selected:
        defn = REGISTRY[name]
        if defn["transport"] == "http":
            entry: dict[str, Any] = {"type": "http", "url": defn["url"]}
            # Bake the agent's own API key as the Bearer header so this
            # agent's MCP calls authenticate AS itself — actions attribute
            # correctly in audit/activity feeds. The registry says which
            # env var carries the key; for agentira-MCP that's the agent's
            # own profile.api_key (the same one passed at chat-API auth).
            if defn.get("auth_env_var") == "AGENTIRA_API_KEY" and agent_api_key:
                entry["headers"] = {"Authorization": f"Bearer {agent_api_key}"}
        elif defn["transport"] == "stdio":
            entry = {"command": defn["command"][0]}
            if len(defn["command"]) > 1:
                entry["args"] = defn["command"][1:]
        else:
            # Future transports (sse, ws) — caller adds them when needed.
            continue

        # Per-server env wiring.
        env: dict[str, str] = {}
        if name == "agentira-project" and repo_path:
            env["AGENTIRA_REPO_PATH"] = repo_path
        if name == "memory" and agent_id:
            scope_proj = project_id or "_no_project"
            if agent_home_path:
                path = os.path.join(
                    os.path.expanduser(agent_home_path),
                    "memory", scope_proj, "memory.json",
                )
            else:
                path = (
                    os.path.expanduser(memory_root)
                    + f"/{agent_id}/{scope_proj}/memory.json"
                )
            env["MEMORY_FILE_PATH"] = path
        if env:
            entry["env"] = env
        mcp_servers[name] = entry

    # Free-form override merge — last-write-wins on name collisions.
    # Accepts either a JSON string or a parsed dict; tolerates either
    # the full shape {"mcpServers": {...}} or just {name: {...}}.
    override_obj: dict[str, Any] | None = None
    if isinstance(mcp_config_override, str) and mcp_config_override.strip():
        import json as _json
        try:
            override_obj = _json.loads(mcp_config_override)
        except Exception:
            override_obj = None
    elif isinstance(mcp_config_override, dict):
        override_obj = mcp_config_override
    if isinstance(override_obj, dict):
        override_servers = override_obj.get("mcpServers")
        if not isinstance(override_servers, dict):
            override_servers = override_obj  # bare {name: {...}} form
        for k, v in (override_servers or {}).items():
            if isinstance(v, dict):
                mcp_servers[k] = v

    # Per-agent kill switch — applied LAST so it can strip auto-injected
    # servers too (e.g. an agent that's intentionally memory-less).
    if disabled_servers:
        for name in disabled_servers:
            mcp_servers.pop(name, None)

    return {"mcpServers": mcp_servers}
