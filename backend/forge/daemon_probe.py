"""Ask the daemon to check MCP servers from the user's machine.

The backend may run in a container whose network differs from the host agents
run on, so its own probe would report URLs as fine that agents can't reach
(or the reverse). The daemon dials them from the host instead.
"""
from __future__ import annotations

from backend.db import get_current_org
from backend.forge.ws_dispatch import hub

NO_DAEMON = "No daemon is online to check from. Start the daemon on your machine."


def _ask_daemon(frame: dict) -> dict | None:
    return hub.request_sync({"type": "mcp_probe", **frame}, org_id=get_current_org())


def probe_tools(url: str, bearer: str | None = None, *, name: str = "s") -> dict:
    """{"ok": True, "tools": [...]} or {"ok": False, "error": "<plain text>"}."""
    reply = _ask_daemon({"servers": [{"name": name, "url": url, "bearer": bearer}]})
    if reply is None:
        return {"ok": False, "error": NO_DAEMON}
    return reply["servers"].get(name) or {"ok": False, "error": "The daemon sent no answer."}


def host_servers() -> dict:
    """MCP servers in the daemon host's own config, each checked from there."""
    reply = _ask_daemon({"servers": [], "host": True})
    if reply is None:
        return {"checked": False, "servers": []}
    return {"checked": True, "servers": reply.get("host", [])}
