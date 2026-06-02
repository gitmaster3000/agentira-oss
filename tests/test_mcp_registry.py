"""Tests for the global MCP server registry + per-run config builder (AP-50).

Covers:
- Registry exposure (list/get).
- Resolution rules in build_mcp_config:
  * auto servers are always included.
  * agent's listed servers are added on top.
  * unknown agent server names are dropped silently.
  * memory server gets a per-(agent, project) MEMORY_FILE_PATH.
- Agent serialization round-trips mcp_servers as a list, not a JSON string.
"""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend.forge import services as forge_services
from backend.forge.mcp_registry import (
    REGISTRY,
    build_mcp_config,
    get_server,
    list_servers,
)


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    # AP-86 merge: create_agent needs a bot role to mint backing profiles.
    # Seed it so tests that call create_agent don't fail with
    # "bot role missing".
    from backend.models import Role
    s = TestSession()
    try:
        s.add(Role(name="bot"))
        s.commit()
    finally:
        s.close()
    with patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.runs.SessionLocal", TestSession):
        yield TestSession


# ── Registry ────────────────────────────────────────────────────────────

def test_registry_has_required_servers():
    """agentira + memory must always be present — finish_run + memory rely on them."""
    assert "agentira" in REGISTRY
    assert "memory" in REGISTRY
    assert REGISTRY["agentira"]["auto"] is True
    assert REGISTRY["memory"]["auto"] is True


def test_list_servers_default_includes_auto():
    names = {s["name"] for s in list_servers()}
    assert "agentira" in names
    assert "memory" in names


def test_list_servers_can_hide_auto_for_picker():
    """The frontend picker calls with include_auto=False — users can't toggle auto servers."""
    names = {s["name"] for s in list_servers(include_auto=False)}
    assert "agentira" not in names
    assert "memory" not in names
    # The only servers in the default registry are auto-injected; with
    # auto hidden the picker returns an empty list (until opt-in servers
    # are reintroduced or added via custom JSON override).
    # Either way: auto MUST be excluded.


def test_get_server_unknown_returns_none():
    assert get_server("nonexistent_xyz") is None


# ── build_mcp_config resolution ─────────────────────────────────────────

def test_auto_servers_always_included():
    cfg = build_mcp_config(
        agent_mcp_servers=None, agent_id="a1", project_id="p1"
    )
    assert "agentira" in cfg["mcpServers"]
    assert "memory" in cfg["mcpServers"]


def test_agent_picks_are_unioned_with_auto():
    # `filesystem` was removed from the default registry; just check that
    # auto servers come through when agent_mcp_servers is empty/unknown.
    cfg = build_mcp_config(
        agent_mcp_servers=["nonexistent_server"], agent_id="a1", project_id="p1"
    )
    assert "nonexistent_server" not in cfg["mcpServers"]
    assert "agentira" in cfg["mcpServers"]
    assert "memory" in cfg["mcpServers"]


def test_unknown_server_names_silently_dropped():
    """A stale agent.mcp_servers value (e.g. server removed from registry)
    must not crash dispatch — drop unknown names and continue."""
    cfg = build_mcp_config(
        agent_mcp_servers=["ghost_server_xyz", "another_ghost"],
        agent_id="a1",
        project_id="p1",
    )
    assert "ghost_server_xyz" not in cfg["mcpServers"]
    assert "another_ghost" not in cfg["mcpServers"]
    # Auto servers still present
    assert "agentira" in cfg["mcpServers"]


def test_memory_path_scoped_per_agent_and_project():
    cfg_a_x = build_mcp_config(
        agent_mcp_servers=None, agent_id="agentA", project_id="projX",
        memory_root="/tmp/mem",
    )
    cfg_a_y = build_mcp_config(
        agent_mcp_servers=None, agent_id="agentA", project_id="projY",
        memory_root="/tmp/mem",
    )
    path_x = cfg_a_x["mcpServers"]["memory"]["env"]["MEMORY_FILE_PATH"]
    path_y = cfg_a_y["mcpServers"]["memory"]["env"]["MEMORY_FILE_PATH"]
    assert path_x != path_y
    assert "agentA" in path_x and "projX" in path_x
    assert "agentA" in path_y and "projY" in path_y


def test_memory_falls_back_when_project_missing():
    """Free-floating chat (no project) still gets a usable memory path."""
    cfg = build_mcp_config(
        agent_mcp_servers=None, agent_id="agentA", project_id=None,
        memory_root="/tmp/mem",
    )
    path = cfg["mcpServers"]["memory"]["env"]["MEMORY_FILE_PATH"]
    assert "agentA" in path
    # Some sentinel for "no project" so paths don't collide with None.
    assert "_no_project" in path


def test_http_server_includes_url_in_config():
    cfg = build_mcp_config(
        agent_mcp_servers=None, agent_id="a1", project_id="p1"
    )
    agentira_entry = cfg["mcpServers"]["agentira"]
    assert agentira_entry["type"] == "http"
    assert agentira_entry["url"].startswith("http")


def test_stdio_server_includes_command_and_args():
    # `memory` is the canonical stdio server now (filesystem was removed).
    cfg = build_mcp_config(
        agent_mcp_servers=None, agent_id="a1", project_id="p1"
    )
    mem = cfg["mcpServers"]["memory"]
    assert "command" in mem
    assert "args" in mem


def test_auto_server_cannot_be_re_added_via_agent_list():
    """Listing 'agentira' in agent.mcp_servers shouldn't double-add or
    de-auto it — set semantics mean it appears exactly once."""
    cfg = build_mcp_config(
        agent_mcp_servers=["agentira"],
        agent_id="a1", project_id="p1",
    )
    assert "agentira" in cfg["mcpServers"]


# ── update_agent persistence ───────────────────────────────────────────

def test_update_agent_persists_mcp_servers_as_list():
    """The agent serializer must return mcp_servers as a list, not a
    JSON string — the frontend picker can't render JSON-as-string."""
    # AP-90: create_agent now requires runtime_id (managed agents are
    # dispatchable by definition). Provide one.
    _runtime = _seed_runtime("claude")
    a = forge_services.create_agent(name="Test Agent", executor_type="cli", runtime_id=_runtime)
    updated = forge_services.update_agent(
        a["id"], mcp_servers=["anything"]
    )
    assert updated["mcp_servers"] == ["anything"]
    fetched = forge_services.get_agent(a["id"])
    assert fetched["mcp_servers"] == ["anything"]


def test_update_agent_can_clear_mcp_servers():
    _runtime = _seed_runtime("claude")
    a = forge_services.create_agent(name="Clearer", executor_type="cli", runtime_id=_runtime)
    forge_services.update_agent(a["id"], mcp_servers=["anything"])
    forge_services.update_agent(a["id"], mcp_servers=[])
    assert forge_services.get_agent(a["id"])["mcp_servers"] == []


def test_new_agent_has_empty_mcp_servers():
    _runtime = _seed_runtime("claude")
    a = forge_services.create_agent(name="New", executor_type="cli", runtime_id=_runtime)
    assert a["mcp_servers"] == []


def _seed_runtime(provider: str) -> str:
    """Helper: register a fake runtime so create_agent's runtime_id FK
    can resolve. Returns the runtime id."""
    res = forge_services.register_runtimes(
        daemon_id="test-daemon",
        device_name="test",
        runtimes=[{
            "provider": provider,
            "binary_path": "/usr/bin/true",
            "version": "0.0.0",
            "capabilities": [],
            "models": [],
        }],
    )
    return res["registered"][0]["id"]
