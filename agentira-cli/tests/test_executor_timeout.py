"""Gateway chat-completions timeout is env-configurable (local models are slow).

Regression guard: local qwen/ollama turns routinely exceed the old hardcoded
120s, which surfaced as a false `timed out` run failure. The timeout must
default high enough for local inference and stay overridable for slower rigs.
"""

import importlib
import os


def _reload_executor():
    import agentira_cli.daemon.executor as ex
    return importlib.reload(ex)


def test_default_timeout_is_generous(monkeypatch):
    monkeypatch.delenv("AGENTIRA_GATEWAY_TIMEOUT", raising=False)
    ex = _reload_executor()
    # Must comfortably exceed the old 120s that tripped local qwen runs.
    assert ex._GATEWAY_TIMEOUT_S >= 300


def test_env_overrides_timeout(monkeypatch):
    monkeypatch.setenv("AGENTIRA_GATEWAY_TIMEOUT", "900")
    ex = _reload_executor()
    assert ex._GATEWAY_TIMEOUT_S == 900


def test_timeout_applied_at_call_site(monkeypatch):
    """The configured value, not a literal, is passed to urlopen."""
    monkeypatch.delenv("AGENTIRA_GATEWAY_TIMEOUT", raising=False)
    ex = _reload_executor()
    src = importlib.import_module("inspect").getsource(ex)
    assert "timeout=_GATEWAY_TIMEOUT_S" in src
    assert "timeout=120" not in src


def teardown_module(module):
    # Leave the module in its env-default state for any later importers.
    os.environ.pop("AGENTIRA_GATEWAY_TIMEOUT", None)
    importlib.reload(importlib.import_module("agentira_cli.daemon.executor"))
