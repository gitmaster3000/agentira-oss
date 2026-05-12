"""Tests for ClaudeRuntime model list — static catalog with env override.

claude-code authenticates via the user's logged-in Anthropic session, not a
developer API key, so we don't introspect /v1/models. The catalog is a
hand-maintained static list (current-generation aliases + a few pinned
dated SKUs), with an env-var escape hatch for power users.
"""

import pytest

agentira_cli_claude = pytest.importorskip(
    "agentira_cli.runtimes.claude",
    reason="agentira-cli package not installed",
)
ClaudeRuntime = agentira_cli_claude.ClaudeRuntime


def test_introspect_returns_empty_without_override(monkeypatch):
    """No override → empty dict so base.detect() falls back to cls.models."""
    monkeypatch.delenv("AGENTIRA_CLAUDE_MODELS", raising=False)
    assert ClaudeRuntime.introspect("/fake/claude") == {}


def test_introspect_honors_env_override(monkeypatch):
    monkeypatch.setenv("AGENTIRA_CLAUDE_MODELS", "claude-opus-4-1, claude-sonnet-4-5")
    result = ClaudeRuntime.introspect("/fake/claude")
    assert result == {"models": ["claude-opus-4-1", "claude-sonnet-4-5"]}


def test_introspect_ignores_blank_override(monkeypatch):
    monkeypatch.setenv("AGENTIRA_CLAUDE_MODELS", "   ,  ,")
    assert ClaudeRuntime.introspect("/fake/claude") == {}


def test_static_models_include_aliases_and_pinned_skus():
    """Aliases ("sonnet"/"opus"/"haiku") for always-latest, plus dated SKUs
    so users can pin an older generation when they need reproducibility."""
    models = ClaudeRuntime.models
    # Aliases present so the dropdown's default is sensibly forward-compatible.
    for alias in ("sonnet", "opus", "haiku"):
        assert alias in models
    # At least one dated SKU so users can pin.
    assert any(m.startswith("claude-") for m in models)
    # Aliases come first so they're the default selection in UIs.
    assert models[0] in ("sonnet", "opus", "haiku")
