"""Discover the tools a remote MCP server offers (initialize + tools/list).

Speaks the streamable-HTTP transport: JSON-RPC over POST, response either
plain JSON or a single SSE `data:` frame. Never raises — a failed probe is a
result the UI renders, not an error.
"""
from __future__ import annotations

import json
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
