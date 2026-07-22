"""Grok CLI adapter contract and subprocess integration coverage."""

from __future__ import annotations

import asyncio
import json

from agentira_cli.daemon.executor import (
    _prepare_grok_mcp_config,
    _restore_grok_mcp_config,
    run_cli_stream,
)
from agentira_cli.runtimes.claude import ResultEvent, TextEvent
from agentira_cli.runtimes.grok import GrokRuntime


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


def test_parse_streaming_text_event():
    event = GrokRuntime.parse_event('{"type":"text","data":"hello"}')

    assert isinstance(event, TextEvent)
    assert event.text == "hello"


def test_parse_streaming_end_event_with_session_and_usage():
    event = GrokRuntime.parse_event(
        '{"type":"end","sessionId":"session-123",'
        '"usage":{"input_tokens":12,"output_tokens":3}}'
    )

    assert isinstance(event, ResultEvent)
    assert event.success is True
    assert event.session_id == "session-123"
    assert event.input_tokens == 12
    assert event.output_tokens == 3


def test_parse_streaming_error_event():
    event = GrokRuntime.parse_event('{"type":"error","message":"bad request"}')

    assert isinstance(event, ResultEvent)
    assert event.success is False
    assert event.error == "bad request"


def test_grok_headless_stream_completes_through_executor(tmp_path):
    """A Grok-shaped subprocess must produce a successful StreamResult.

    The fake executable rejects the regression's ``--verbose`` flag and the
    Claude-only ``stream-json`` spelling, then emits Grok's real ``text`` and
    terminal ``end`` frames. This reproduces the prior clean-exit/no-result
    failure through the complete executor path.
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
print(json.dumps({'type': 'text', 'data': 'ok'}))
print(json.dumps({
    'type': 'end',
    'sessionId': 'session-123',
    'usage': {'input_tokens': 12, 'output_tokens': 3},
}))
"""
    )
    binary.chmod(0o755)

    batches = []

    async def on_event(events):
        batches.extend(events)

    result = asyncio.run(
        run_cli_stream(
            GrokRuntime,
            str(binary),
            "reply OK",
            workdir=str(tmp_path),
            on_event=on_event,
        )
    )

    assert result.success is True
    assert result.session_id == "session-123"
    assert result.input_tokens == 12
    assert result.output_tokens == 3
    assert batches == [{"type": "text", "text": "ok", "model": ""}]
