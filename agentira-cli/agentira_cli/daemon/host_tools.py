"""Discover the host-side tools a runtime brings on its own.

The daemon runs on the user's machine, so it's the only place that can
read `~/.claude.json`, `~/.claude/CLAUDE.md`, and similar host config.
We collect those at startup and ship them up at runtime registration —
the UI's Toolset tab uses them to render the three-layer view:

  Layer 1 — runtime built-ins (Read/Edit/Bash/...)  ← static per provider
  Layer 2 — user's host MCP + md files               ← discovered here
  Layer 3 — Agentira-managed (agentira/memory/...)   ← from registry

Best-effort: a missing or unreadable host file just returns an empty
list, never raises.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Layer 1 — what each runtime ships with built-in. Hardcoded because
# these are stable per binary version and not introspectable without
# running the binary in a special mode.
BUILTIN_TOOLS: dict[str, list[str]] = {
    "claude": [
        "Read", "Edit", "Write", "Bash", "Grep", "Glob",
        "WebFetch", "WebSearch", "Task", "TodoWrite",
        "NotebookEdit", "BashOutput", "KillShell",
    ],
    "codex": [
        # Codex CLI's built-in toolset — best-effort, may drift.
        "read_file", "edit_file", "shell", "search",
    ],
    "gemini": [
        # Gemini CLI's built-in toolset — best-effort.
        "read_file", "write_file", "shell", "search",
    ],
    "openclaw": [],  # OpenClaw's tools come via its workspace, not built-in
    "ollama": [],    # Bare LLM gateway, no built-ins
}


def discover_for(provider: str) -> dict:
    """Return host-side tools dict for the given runtime provider."""
    out: dict = {
        "builtins": BUILTIN_TOOLS.get(provider, []),
        "host_mcp_servers": [],
        "host_md_files": [],
    }
    if provider == "claude":
        out["host_mcp_servers"] = _discover_claude_mcp()
        out["host_md_files"] = _discover_md_files([
            "~/.claude/CLAUDE.md",
        ])
    elif provider == "codex":
        out["host_md_files"] = _discover_md_files(["~/.codex/AGENTS.md"])
    elif provider == "gemini":
        out["host_md_files"] = _discover_md_files(["~/.gemini/GEMINI.md"])
    elif provider == "openclaw":
        out["host_mcp_servers"] = _discover_openclaw_tools()
    return out


def _discover_claude_mcp() -> list[dict]:
    """Read user MCP servers from ~/.claude.json."""
    path = Path.home() / ".claude.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    servers = data.get("mcpServers") or {}
    out: list[dict] = []
    for name, defn in servers.items():
        if not isinstance(defn, dict):
            continue
        # Classify transport — claude-code accepts stdio (command+args)
        # or http (type=http, url). We don't care which here, just hint.
        transport = "http" if defn.get("type") == "http" or "url" in defn else "stdio"
        out.append({
            "name": name,
            "transport": transport,
            "url": defn.get("url", "") if transport == "http" else "",
            "command": (defn.get("command") or "") if transport == "stdio" else "",
        })
    return out


def _discover_openclaw_tools() -> list[dict]:
    """Best-effort: read the `agentira-runner` entry's tool profile from
    ~/.openclaw/openclaw.json so the UI can show which OpenClaw tools the
    runner-agent has access to."""
    path = Path.home() / ".openclaw" / "openclaw.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    agents = data.get("agents") or []
    runner = next(
        (a for a in agents if isinstance(a, dict) and a.get("id") == "agentira-runner"),
        None,
    )
    if not runner:
        return []
    tools = runner.get("tools") or {}
    profile = tools.get("profile", "")
    # Profile is a named bundle (full, minimal, custom). Surface as a
    # single pseudo-entry until OpenClaw exposes a per-tool listing.
    return [{
        "name": f"openclaw:{profile or 'default'}",
        "transport": "platform",
        "url": "",
        "command": "",
    }]


def _discover_md_files(paths: list[str]) -> list[dict]:
    """Return existence + size for each expanded path."""
    out: list[dict] = []
    for p in paths:
        expanded = os.path.expanduser(p)
        if os.path.exists(expanded):
            try:
                size = os.path.getsize(expanded)
            except OSError:
                size = 0
            out.append({"path": p, "size": size})
    return out
