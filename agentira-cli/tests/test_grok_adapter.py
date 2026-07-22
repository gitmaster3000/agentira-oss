"""Grok CLI adapter contract and subprocess integration coverage."""

from __future__ import annotations

import json
import subprocess

from agentira_cli.runtimes.grok import GrokRuntime
from agentira_cli.daemon.executor import (
    _prepare_grok_mcp_config,
    _restore_grok_mcp_config,
)


def test_build_args_uses_grok_headless_options():
    args = GrokRuntime.build_args(
        "fix the bug",
        model="grok-build",
        system_prompt="Be concise.",
        resume_session_id="session-123",
        allowed_tools=("Read", "Write"),
    )

    assert args[:4] == ["--single", "fix the bug", "--output-format", "streaming-json"]
    assert "--verbose" not in args
    assert "stream-json" not in args
    assert ["--system-prompt-override", "Be concise."] == args[args.index("--system-prompt-override"):args.index("--system-prompt-override") + 2]
    assert args[-4:] == ["--allow", "Read", "--allow", "Write"]


def test_build_args_does_not_emit_unsupported_mcp_flags():
    args = GrokRuntime.build_args(
        "hello",
        mcp_config_path="/tmp/mcp.json",
        mcp_strict=True,
    )

    assert "--mcp-config" not in args
    assert "--strict-mcp-config" not in args
    assert "mcp_config" in GrokRuntime.capabilities


def test_grok_mcp_bundle_is_materialized_and_restored(tmp_path):
    config = '{"mcpServers": {"agentira": {"url": "https://example.test/mcp"}}}'
    path, original = _prepare_grok_mcp_config(config, str(tmp_path))

    assert (tmp_path / ".mcp.json").exists()
    materialized = json.loads((tmp_path / ".mcp.json").read_text())
    assert materialized["mcpServers"]["agentira"]["url"] == "https://example.test/mcp"

    _restore_grok_mcp_config(path, original)
    assert not (tmp_path / ".mcp.json").exists()


def test_grok_headless_command_accepts_adapter_args(tmp_path):
    """Integration check: a Grok-shaped CLI accepts the generated argv.

    The fake executable rejects the regression's ``--verbose`` flag and the
    Claude-only ``stream-json`` spelling, then emits a streaming JSON event.
    This exercises the adapter through a real subprocess boundary without
    requiring a logged-in Grok session or network access.
    """
    binary = tmp_path / "grok"
    binary.write_text(
        """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if '--verbose' in args or 'stream-json' in args:
    raise SystemExit(2)
if args[0:1] != ['--single'] or args[args.index('--output-format') + 1] != 'streaming-json':
    raise SystemExit(3)
print(json.dumps({'type': 'result', 'text': 'ok'}))
"""
    )
    binary.chmod(0o755)

    result = subprocess.run(
        [str(binary), *GrokRuntime.build_args("reply OK")],
        capture_output=True,
        text=True,
        check=True,
    )

    assert GrokRuntime.parse_event(result.stdout).get("text") == "ok"
