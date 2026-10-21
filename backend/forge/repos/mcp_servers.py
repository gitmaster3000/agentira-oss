"""Data access for the org-wide MCP server registry (mcp_servers table)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from backend import secret_box
from backend.models import McpServer


def list_all(db) -> list[McpServer]:
    return db.query(McpServer).order_by(McpServer.name).all()


def get(db, server_id: str) -> McpServer | None:
    return db.get(McpServer, server_id)


def create(db, *, name: str, url: str, description: str = "",
           auth_mode: str = "none", token: str | None = None) -> McpServer:
    row = McpServer(name=name, url=url, description=description,
                    auth_mode=auth_mode, token=secret_box.encrypt(token))
    db.add(row)
    db.flush()
    return row


def update(db, row: McpServer, fields: dict) -> McpServer:
    """Apply a partial update. `token` is write-only: a missing/None value
    keeps the stored one, an empty string clears it."""
    for key in ("description", "url", "auth_mode", "enabled"):
        if key in fields and fields[key] is not None:
            setattr(row, key, fields[key])
    if fields.get("token") is not None:
        row.token = secret_box.encrypt(fields["token"]) or None
    db.flush()
    return row


def delete(db, row: McpServer) -> None:
    db.delete(row)
    db.flush()


def save_probe(db, row: McpServer, result: dict) -> McpServer:
    row.checked_at = datetime.now(timezone.utc)
    if result["ok"]:
        row.status, row.status_detail = "ok", None
        row.tools = json.dumps(result["tools"])
    else:
        row.status, row.status_detail = "error", result["error"][:300]
    db.flush()
    return row


def token_of(row: McpServer) -> str | None:
    return secret_box.decrypt(row.token)


def tools_of(row: McpServer) -> list[dict]:
    return json.loads(row.tools) if row.tools else []


def runtime_map(db) -> dict[str, dict]:
    """name -> definition for every enabled server, in the REGISTRY entry
    shape plus the secret and cached tools. Server-side use only."""
    return {
        r.name: {"transport": "http", "url": r.url, "description": r.description,
                 "auth_mode": r.auth_mode, "token": token_of(r),
                 "tool_names": [t["name"] for t in tools_of(r)]}
        for r in list_all(db) if r.enabled
    }
