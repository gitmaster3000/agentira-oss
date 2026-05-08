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
        "url": os.environ.get("AGENTIRA_MCP_URL", "http://mcp:8000/mcp"),
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
    "filesystem": {
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
        "auth_env_var": None,
        "description": "Read/write files within the workdir. Opt-in.",
        "auto": False,
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
    # agent's choices, filtered against the registry
    for name in (agent_mcp_servers or []):
        if name in REGISTRY and not REGISTRY[name].get("auto"):
            selected.add(name)

    mcp_servers: dict[str, Any] = {}
    for name in selected:
        defn = REGISTRY[name]
        if defn["transport"] == "http":
            entry: dict[str, Any] = {"type": "http", "url": defn["url"]}
        elif defn["transport"] == "stdio":
            entry = {"command": defn["command"][0]}
            if len(defn["command"]) > 1:
                entry["args"] = defn["command"][1:]
        else:
            # Future transports (sse, ws) — caller adds them when needed.
            continue

        # Per-server env wiring. Memory gets a scoped path so per-(agent,
        # project) memory falls out of the env var without an overlay
        # table.
        env: dict[str, str] = {}
        if name == "memory" and agent_id:
            scope_proj = project_id or "_no_project"
            path = (
                os.path.expanduser(memory_root)
                + f"/{agent_id}/{scope_proj}/memory.json"
            )
            env["MEMORY_FILE_PATH"] = path
        if env:
            entry["env"] = env
        mcp_servers[name] = entry

    return {"mcpServers": mcp_servers}
