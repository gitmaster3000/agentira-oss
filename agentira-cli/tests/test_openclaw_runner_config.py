"""ensure_runner_agent must (re)configure the runner even when it already
exists — empty systemPromptOverride + tools.profile=full.

Regression: the config block used to run only right after `agents add`, so a
runner created by an older build (before the tools logic) never got
tools.profile=full and its tools stayed unconfigured. subprocess is mocked;
no live OpenClaw needed.
"""

from __future__ import annotations

import json
from unittest import mock

from agentira_cli.runtimes.openclaw import ensure_runner_agent, _RUNNER_AGENT_ID


def _run_factory(list_payload):
    """Return a subprocess.run stub + a record of every argv it saw."""
    calls: list[list[str]] = []

    def _run(argv, *a, **k):
        calls.append(argv)
        if argv[:3] == ["openclaw", "agents", "list"]:
            return mock.Mock(returncode=0, stdout=json.dumps(list_payload), stderr="")
        return mock.Mock(returncode=0, stdout="", stderr="")

    return _run, calls


def _config_sets(calls):
    return [c for c in calls if c[:3] == ["openclaw", "config", "set"]]


def test_existing_runner_still_gets_reconfigured():
    # Runner already present at index 1; must NOT re-add, but MUST config-set.
    present = [
        {"id": "main", "isDefault": True, "model": "ollama/qwen3.6"},
        {"id": _RUNNER_AGENT_ID, "model": "ollama/qwen3.6"},
    ]
    run, calls = _run_factory(present)
    with mock.patch("subprocess.run", side_effect=run):
        created = ensure_runner_agent()

    assert created is False, "existing runner should not be reported as created"
    assert not any(c[:3] == ["openclaw", "agents", "add"] for c in calls), \
        "must not re-add an existing runner"
    sets = _config_sets(calls)
    paths = {c[3] for c in sets}
    assert any(p.endswith(".systemPromptOverride") for p in paths)
    assert any(p.endswith(".tools") for p in paths)
    tools_val = next(c[4] for c in sets if c[3].endswith(".tools"))
    assert json.loads(tools_val) == {"profile": "full"}


def test_new_runner_is_added_then_configured():
    # Only a default agent exists; runner gets added, then configured.
    # agents list is called twice: before add (no runner) and inside
    # _configure_runner (runner now present).
    before = [{"id": "main", "isDefault": True, "model": "ollama/qwen3.6"}]
    after = before + [{"id": _RUNNER_AGENT_ID, "model": "ollama/qwen3.6"}]
    seq = [before, after]

    def _run(argv, *a, **k):
        if argv[:3] == ["openclaw", "agents", "list"]:
            payload = seq.pop(0) if seq else after
            return mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")
        return mock.Mock(returncode=0, stdout="", stderr="")

    calls: list[list[str]] = []

    def _rec(argv, *a, **k):
        calls.append(argv)
        return _run(argv, *a, **k)

    with mock.patch("subprocess.run", side_effect=_rec):
        created = ensure_runner_agent(default_model="ollama/qwen3.6")

    assert created is True
    assert any(c[:3] == ["openclaw", "agents", "add"] for c in calls)
    assert _config_sets(calls), "new runner must be configured after add"
