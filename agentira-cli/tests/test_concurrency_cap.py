"""Daemon max-concurrent-runs cap is env-configurable.

The old hardcoded Semaphore(3) capped the whole fleet at 3 simultaneous runs,
so 5 conductor-enabled agents could never all run at once. The cap now reads
AGENTIRA_MAX_CONCURRENT_RUNS (default 8) with a floor of 1.
"""

import importlib
import os


def _reload_core():
    import agentira_cli.daemon.core as core
    return importlib.reload(core)


def test_default_cap_covers_five_agents(monkeypatch):
    monkeypatch.delenv("AGENTIRA_MAX_CONCURRENT_RUNS", raising=False)
    core = _reload_core()
    assert core._MAX_CONCURRENT_RUNS >= 5


def test_env_overrides_cap(monkeypatch):
    monkeypatch.setenv("AGENTIRA_MAX_CONCURRENT_RUNS", "12")
    core = _reload_core()
    assert core._MAX_CONCURRENT_RUNS == 12


def test_cap_has_floor_of_one(monkeypatch):
    monkeypatch.setenv("AGENTIRA_MAX_CONCURRENT_RUNS", "0")
    core = _reload_core()
    assert core._MAX_CONCURRENT_RUNS == 1


def teardown_module(module):
    os.environ.pop("AGENTIRA_MAX_CONCURRENT_RUNS", None)
    importlib.reload(importlib.import_module("agentira_cli.daemon.core"))
