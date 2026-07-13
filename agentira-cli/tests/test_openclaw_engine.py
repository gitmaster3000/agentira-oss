"""1:1 OpenClaw engine agents — session routing + workspace bind."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from agentira_cli.runtimes import openclaw_engine as eng
from agentira_cli.runtimes.openclaw import OpenClawRuntime


def test_engine_agent_id_stable():
    assert eng.engine_agent_id("f97902c47004") == "ar-f97902c4"
    assert eng.engine_agent_id("F97902C47004") == "ar-f97902c4"
    assert eng.engine_agent_id("") == "ar-unknown"


def test_derive_session_key_routes_to_engine_agent():
    key = eng.derive_engine_session_key(
        agent_id="f97902c47004", scope_key="task:9af8cdc493c3",
    )
    assert key == "agent:ar-f97902c4:task:9af8cdc493c3"
    # OpenClaw parseAgentSessionKey needs agent:<id>:<rest>
    assert key.startswith("agent:ar-")


def test_openclaw_runtime_derive_matches_engine():
    k = OpenClawRuntime.derive_session_handle(
        agent_id="f97902c47004", scope_key="task:abc",
    )
    assert k == "agent:ar-f97902c4:task:abc"


def test_normalize_upgrades_legacy_agentira_key():
    legacy = "agentira:f97902c4:task:9af8cdc493c3"
    got = eng.normalize_session_key(
        legacy, agent_id="f97902c47004", scope_key="task:9af8cdc493c3",
    )
    assert got == "agent:ar-f97902c4:task:9af8cdc493c3"


def test_normalize_preserves_agent_prefixed_keys():
    k = "agent:ar-f97902c4:chat:default"
    assert eng.normalize_session_key(k, agent_id="f97902c47004") == k


def test_bind_workspace_if_changed_writes_once(tmp_path):
    eng.reset_bind_cache()
    desk = tmp_path / "task-desk"
    desk.mkdir()
    agents = [
        {"id": "main", "workspace": "/old"},
        {"id": "ar-f97902c4", "workspace": str(tmp_path / "other")},
    ]
    sets: list[list[str]] = []

    def _run(argv, *a, **k):
        sets.append(list(argv))
        return mock.Mock(returncode=0, stdout="", stderr="")

    with mock.patch("subprocess.run", side_effect=_run):
        changed = eng.bind_workspace_if_changed(
            "ar-f97902c4", str(desk), binary_path="openclaw", agents=agents,
        )
        assert changed is True
        # Second bind same path — cache hits, no CLI.
        changed2 = eng.bind_workspace_if_changed(
            "ar-f97902c4", str(desk), binary_path="openclaw", agents=agents,
        )
        assert changed2 is False

    config_sets = [c for c in sets if c[:3] == ["openclaw", "config", "set"]]
    assert len(config_sets) == 1
    assert config_sets[0][3] == "agents.list[1].workspace"
    assert config_sets[0][4] == str(desk.resolve())


def test_ensure_engine_agent_adds_when_missing(tmp_path):
    eng.reset_bind_cache()
    desk = tmp_path / "desk"
    desk.mkdir()
    calls: list[list[str]] = []
    state = {"listed": 0}

    def _run(argv, *a, **k):
        calls.append(list(argv))
        if argv[:3] == ["openclaw", "agents", "list"]:
            state["listed"] += 1
            # First list: empty of engine; later lists include it.
            if state["listed"] == 1:
                payload = [{"id": "main", "isDefault": True, "model": "m"}]
            else:
                payload = [
                    {"id": "main", "isDefault": True, "model": "m"},
                    {"id": "ar-abcd1234", "workspace": str(desk), "model": "m"},
                ]
            return mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")
        return mock.Mock(returncode=0, stdout="", stderr="")

    with mock.patch("subprocess.run", side_effect=_run):
        eid = eng.ensure_engine_agent(
            "abcd1234ffff", workdir=str(desk), default_model="m",
        )
    assert eid == "ar-abcd1234"
    adds = [c for c in calls if c[:3] == ["openclaw", "agents", "add"]]
    assert adds, "must create engine agent"
    assert "ar-abcd1234" in adds[0]
    assert "--workspace" in adds[0]
