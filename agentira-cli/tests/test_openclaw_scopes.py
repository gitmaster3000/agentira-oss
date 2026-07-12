"""Unit tests for OpenClaw scope discovery helpers."""
from __future__ import annotations

from agentira_cli.runtimes.openclaw_scopes import (
    WRITE_SCOPE_FALLBACK,
    default_requested_scopes,
    discover_write_scope,
)


def test_fallback_constant():
    assert WRITE_SCOPE_FALLBACK == "operator.write"


def test_default_requested_scopes_include_write():
    scopes = default_requested_scopes()
    assert "operator.read" in scopes
    assert "operator.write" in scopes
    assert discover_write_scope() in scopes
