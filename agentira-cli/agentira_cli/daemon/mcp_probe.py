"""Discover the tools a remote MCP server offers (initialize + tools/list).

Runs on the daemon host, because that is where agents dial the servers from:
a URL that only resolves inside the backend's container (host.docker.internal)
must read as unreachable here. `run_frame` answers the backend's `mcp_probe`
frame for both workspace-registered servers and the host's own ~/.claude.json.

Speaks the streamable-HTTP transport: JSON-RPC over POST, response either
plain JSON or a single SSE `data:` frame. Never raises — a failed probe is a
result the UI renders, not an error.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

_HEADERS = {"Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"}
_PROTOCOL = "2025-03-26"


def _rpc_payload(resp: httpx.Response) -> dict:
    """The JSON-RPC message in a plain-JSON or SSE response body."""
    text = resp.text
    if "text/event-stream" in resp.headers.get("content-type", ""):
        for line in text.splitlines():
            if line.startswith("data:"):
                text = line[5:].strip()
                break
    return json.loads(text) if text.strip() else {}


def _post(client: httpx.Client, url: str, headers: dict, body: dict) -> dict:
    resp = client.post(url, headers=headers, json=body)
    if resp.status_code in (401, 403):
        raise PermissionError(f"Server rejected the credentials (HTTP {resp.status_code}).")
    resp.raise_for_status()
    msg = _rpc_payload(resp)
    if "error" in msg:
        raise RuntimeError(msg["error"].get("message", "MCP error"))
    return msg


def _normalize(tool: dict[str, Any]) -> dict[str, Any]:
    ann = tool.get("annotations") or {}
    return {
        "name": tool["name"],
        "description": (tool.get("description") or "")[:300],
        "read_only": bool(ann.get("readOnlyHint", False)),
    }


def probe_tools(url: str, bearer: str | None = None, *, timeout: float = 10.0) -> dict:
    """{"ok": True, "tools": [...]} or {"ok": False, "error": "<plain text>"}."""
    headers = dict(_HEADERS)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            init = client.post(url, headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": _PROTOCOL, "capabilities": {},
                           "clientInfo": {"name": "agentira", "version": "1"}}})
            if init.status_code in (401, 403):
                raise PermissionError(
                    f"Server rejected the credentials (HTTP {init.status_code}).")
            init.raise_for_status()
            sid = init.headers.get("mcp-session-id")
            if sid:
                headers["Mcp-Session-Id"] = sid
            client.post(url, headers=headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized"})
            msg = _post(client, url, headers,
                        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = [_normalize(t) for t in (msg.get("result") or {}).get("tools", [])]
        return {"ok": True, "tools": tools}
    except PermissionError as e:
        return {"ok": False, "error": str(e)}
    except httpx.TimeoutException:
        return {"ok": False, "error": "Server did not answer in time."}
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"Could not reach the server ({e.__class__.__name__})."}
    except (ValueError, KeyError, RuntimeError) as e:
        return {"ok": False, "error": f"Unexpected reply from server: {e}"[:300]}


def _read_claude_json() -> dict:
    try:
        return json.loads((Path.home() / ".claude.json").read_text())
    except Exception:  # noqa: BLE001 — missing/unreadable host config is just "none"
        return {}


def _host_entry(name: str, defn: dict) -> dict:
    """Probe one ~/.claude.json server with its own header; the secret never
    leaves this process."""
    if defn.get("type") != "http" and "url" not in defn:
        return {"name": name, "transport": "stdio", "url": "",
                "command": defn.get("command") or "", "ok": None, "tools": [], "error": ""}
    url = defn.get("url") or ""
    auth = (defn.get("headers") or {}).get("Authorization", "")
    res = probe_tools(url, auth[7:] if auth.lower().startswith("bearer ") else None)
    return {"name": name, "transport": "http", "url": url, "command": "",
            "ok": res["ok"], "tools": res.get("tools", []), "error": res.get("error", "")}


def run_frame(frame: dict, *, claude_json: dict | None = None) -> dict:
    """Answer an `mcp_probe` frame: {request_id, servers:[{name,url,bearer}], host?}."""
    servers = {s["name"]: probe_tools(s["url"], s.get("bearer"))
               for s in frame.get("servers", [])}
    host: list[dict] = []
    if frame.get("host"):
        cfg = _read_claude_json() if claude_json is None else claude_json
        host = [_host_entry(n, d) for n, d in (cfg.get("mcpServers") or {}).items()
                if isinstance(d, dict)]
    return {"type": "reply", "request_id": frame["request_id"], "servers": servers, "host": host}
