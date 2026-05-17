"""AP-103: register_agentira_mcps — write Agentira MCP servers into
OpenClaw config via `openclaw mcp set`.

subprocess is mocked — no live OpenClaw needed. We verify each server
entry is passed verbatim as a JSON arg and that failures are collected
rather than raised.
"""

from __future__ import annotations

import json
from unittest import mock

from agentira_cli.runtimes.openclaw import register_agentira_mcps


def _ok(*a, **k):
    return mock.Mock(returncode=0, stdout="", stderr="")


def test_registers_each_server_via_mcp_set():
    cfg = {"mcpServers": {
        "agentira": {"type": "http", "url": "http://x/mcp",
                     "headers": {"Authorization": "Bearer KEY1"}},
        "agentira-project": {"command": "python3",
                             "args": ["-m", "agentira_cli.mcp.agentira_project"],
                             "env": {"AGENTIRA_REPO_PATH": "/repo"}},
    }}
    with mock.patch("subprocess.run", side_effect=_ok) as run:
        result = register_agentira_mcps(cfg)

    assert set(result["registered"]) == {"agentira", "agentira-project"}
    assert result["failed"] == []
    # Each call is `openclaw mcp set <name> <json>` with the entry verbatim.
    calls = {c.args[0][3]: c.args[0] for c in run.call_args_list}
    assert json.loads(calls["agentira"][4])["headers"]["Authorization"] == "Bearer KEY1"
    assert json.loads(calls["agentira-project"][4])["env"]["AGENTIRA_REPO_PATH"] == "/repo"
    for argv in calls.values():
        assert argv[:3] == ["openclaw", "mcp", "set"]


def test_per_agent_token_is_what_gets_written():
    """Identity is per-agent: whatever token build_mcp_config baked in is
    exactly what reaches `openclaw mcp set` — the daemon calls this per
    dispatch, so the global slot always holds the current agent's token."""
    cfg = {"mcpServers": {"agentira": {"type": "http", "url": "u",
                                       "headers": {"Authorization": "Bearer AGENT_B"}}}}
    with mock.patch("subprocess.run", side_effect=_ok) as run:
        register_agentira_mcps(cfg)
    written = json.loads(run.call_args_list[0].args[0][4])
    assert written["headers"]["Authorization"] == "Bearer AGENT_B"


def test_failed_server_collected_not_raised():
    def _mixed(argv, **k):
        name = argv[3]
        if name == "memory":
            return mock.Mock(returncode=1, stdout="", stderr="bad json")
        return mock.Mock(returncode=0, stdout="", stderr="")
    cfg = {"mcpServers": {
        "agentira": {"type": "http", "url": "u"},
        "memory": {"command": "npx", "args": ["-y", "x"]},
    }}
    with mock.patch("subprocess.run", side_effect=_mixed):
        result = register_agentira_mcps(cfg)
    assert result["registered"] == ["agentira"]
    assert len(result["failed"]) == 1
    assert result["failed"][0]["name"] == "memory"


def test_missing_openclaw_binary_is_non_fatal():
    cfg = {"mcpServers": {"agentira": {"type": "http", "url": "u"}}}
    with mock.patch("subprocess.run", side_effect=FileNotFoundError("no openclaw")):
        result = register_agentira_mcps(cfg)
    assert result["registered"] == []
    assert result["failed"][0]["name"] == "agentira"


def test_empty_config_is_noop():
    with mock.patch("subprocess.run", side_effect=_ok) as run:
        result = register_agentira_mcps({"mcpServers": {}})
    assert result == {"registered": [], "failed": []}
    run.assert_not_called()
