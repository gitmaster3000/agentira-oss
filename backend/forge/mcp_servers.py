"""Org-wide MCP server registry: add, test, list. Thin layer over the repo
and the tool probe; the router calls these and `build_mcp_config` reads the
result at dispatch."""
from __future__ import annotations

import re

from backend.db import SessionLocal
from backend.forge.mcp_probe import probe_tools
from backend.forge.mcp_registry import REGISTRY
from backend.forge.repos import mcp_servers as repo

AUTH_MODES = ("none", "bearer", "agent_key")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")


def _view(row) -> dict:
    return {
        "id": row.id, "name": row.name, "description": row.description,
        "url": row.url, "auth_mode": row.auth_mode, "has_token": bool(row.token),
        "enabled": row.enabled, "status": row.status,
        "status_detail": row.status_detail,
        "checked_at": row.checked_at.isoformat() if row.checked_at else None,
        "tools": repo.tools_of(row),
    }


def _validate(*, url: str | None = None, auth_mode: str | None = None) -> None:
    if url is not None and not re.match(r"^https?://\S+$", url):
        raise ValueError("URL must start with http:// or https://")
    if auth_mode is not None and auth_mode not in AUTH_MODES:
        raise ValueError(f"auth_mode must be one of {', '.join(AUTH_MODES)}")


def _probe(db, row, bearer: str | None) -> None:
    """Probe with the row's own credential; `agent_key` rows use the
    caller's token, since no agent is in scope when testing."""
    cred = bearer if row.auth_mode == "agent_key" else repo.token_of(row)
    repo.save_probe(db, row, probe_tools(row.url, cred))


def list_view() -> list[dict]:
    with SessionLocal() as db:
        return [_view(r) for r in repo.list_all(db)]


def picker_entries() -> list[dict]:
    """Enabled servers in the agent-form picker shape."""
    with SessionLocal() as db:
        return [{"name": r.name, "transport": "http", "description": r.description,
                 "auto": False, "custom": True, "tools": repo.tools_of(r)}
                for r in repo.list_all(db) if r.enabled]


def create(*, name: str, url: str, description: str = "", auth_mode: str = "none",
           token: str | None = None, bearer: str | None = None) -> dict:
    name = name.strip().lower()
    if not _NAME_RE.match(name):
        raise ValueError("Name must be 2-40 characters: lowercase letters, digits, - or _.")
    if name in REGISTRY:
        raise ValueError(f"'{name}' is a built-in server name.")
    _validate(url=url, auth_mode=auth_mode)
    with SessionLocal() as db:
        if any(r.name == name for r in repo.list_all(db)):
            raise ValueError(f"A server named '{name}' already exists.")
        row = repo.create(db, name=name, url=url, description=description,
                          auth_mode=auth_mode, token=token)
        _probe(db, row, bearer)
        db.commit()
        return _view(row)


def update(server_id: str, fields: dict, *, bearer: str | None = None) -> dict | None:
    _validate(url=fields.get("url"), auth_mode=fields.get("auth_mode"))
    with SessionLocal() as db:
        row = repo.get(db, server_id)
        if row is None:
            return None
        repo.update(db, row, fields)
        if {"url", "auth_mode", "token"} & fields.keys():
            _probe(db, row, bearer)
        db.commit()
        return _view(row)


def test(server_id: str, *, bearer: str | None = None) -> dict | None:
    with SessionLocal() as db:
        row = repo.get(db, server_id)
        if row is None:
            return None
        _probe(db, row, bearer)
        db.commit()
        return _view(row)


def delete(server_id: str) -> bool:
    with SessionLocal() as db:
        row = repo.get(db, server_id)
        if row is None:
            return False
        repo.delete(db, row)
        db.commit()
        return True
