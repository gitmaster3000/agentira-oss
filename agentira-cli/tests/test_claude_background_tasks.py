"""Non-interactive Claude turns must not strand background commands."""

from __future__ import annotations

import asyncio
import json
import stat

from agentira_cli.runtimes.base import TurnRequest
from agentira_cli.runtimes.claude import (
    BACKGROUND_TASK_CONTRACT,
    BACKGROUND_TASK_RESUME_NUDGE,
    ClaudeRuntime,
)


def test_noninteractive_prompt_forbids_background_commands():
    args = ClaudeRuntime.build_args("do the work", system_prompt="Be careful.")
    prompt = args[args.index("--append-system-prompt") + 1]

    assert "Be careful." in prompt
    assert BACKGROUND_TASK_CONTRACT in prompt
    assert "never run commands in the background" in prompt.lower()


def test_fake_background_stream_resumes_once_with_foreground_nudge(tmp_path):
    """A real subprocess stream ending with a live task gets one resumed turn."""
    invocation_log = tmp_path / "invocations.jsonl"
    fake_claude = tmp_path / "fake-claude"
    fake_claude.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
with open(os.environ["INVOCATION_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\\n")

if "--resume" not in args:
    print(json.dumps({"type": "system", "session_id": "session-bg-1"}))
    print(json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "id": "tool-bg-1",
            "name": "Bash",
            "input": {"command": "pytest", "run_in_background": True},
        }]},
    }))
    print(json.dumps({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": "tool-bg-1",
            "content": "Command running in background with ID: bg-123.",
        }]},
    }))
    print(json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "text",
            "text": "Waiting for completion notice.",
        }]},
    }))
else:
    assert args[args.index("--resume") + 1] == "session-bg-1"
    assert any("background task was killed" in arg.lower() for arg in args)
    print(json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "id": "tool-finish-1",
            "name": "mcp__agentira__finish_run",
            "input": {"outcome": "succeeded"},
        }]},
    }))
    print(json.dumps({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": "tool-finish-1",
            "content": "{\\\"ok\\\": true}",
        }]},
    }))

print(json.dumps({
    "type": "result",
    "subtype": "success",
    "result": "turn ended",
    "usage": {"input_tokens": 2, "output_tokens": 3},
}))
""",
        encoding="utf-8",
    )
    fake_claude.chmod(fake_claude.stat().st_mode | stat.S_IXUSR)

    result = asyncio.run(ClaudeRuntime.execute_turn(TurnRequest(
        prompt="run the tests and finish",
        binary_path=str(fake_claude),
        workdir=str(tmp_path),
        env_extra={"INVOCATION_LOG": str(invocation_log)},
    )))

    invocations = [json.loads(line) for line in invocation_log.read_text().splitlines()]
    assert len(invocations) == 2
    assert BACKGROUND_TASK_RESUME_NUDGE in invocations[1]
    assert result.success is True
    assert result.background_tasks_live is False
    assert result.finish_run_called is True
    assert result.input_tokens == 4
    assert result.output_tokens == 6


def test_second_background_end_turn_fails_instead_of_silently_completing(
    monkeypatch,
):
    from agentira_cli.daemon import executor

    calls = []

    async def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        result = executor.StreamResult()
        result.success = True
        result.session_id = "session-bg-2"
        result.background_tasks_live = True
        return result

    monkeypatch.setattr(executor, "run_cli_stream", fake_run)

    result = asyncio.run(ClaudeRuntime.execute_turn(TurnRequest(
        prompt="work",
        binary_path="claude",
    )))

    assert len(calls) == 2
    assert result.success is False
    assert "background task" in result.error.lower()


def test_recovery_without_finish_run_is_failed_not_silent(monkeypatch):
    from agentira_cli.daemon import executor

    calls = 0

    async def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = executor.StreamResult()
        result.success = True
        result.session_id = "session-bg-3"
        result.background_tasks_live = calls == 1
        return result

    monkeypatch.setattr(executor, "run_cli_stream", fake_run)

    result = asyncio.run(ClaudeRuntime.execute_turn(TurnRequest(
        prompt="work",
        binary_path="claude",
    )))

    assert calls == 2
    assert result.success is False
    assert "without calling finish_run" in result.error
