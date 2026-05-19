"""claude-code stream-json `result` parsing + the max-turns cap.

A non-success result (notably error_max_turns — the agent hit the turn
cap) must surface a legible error, not fall through to a bare
"subprocess exited with code N".
"""

from __future__ import annotations

import json

from agentira_cli.runtimes.claude import (
    ClaudeRuntime, parse_stream_line, ResultEvent,
)


def _result(**fields) -> ResultEvent:
    ev = parse_stream_line(json.dumps({"type": "result", "usage": {}, **fields}))
    assert isinstance(ev, ResultEvent)
    return ev


def test_success_result():
    ev = _result(subtype="success", result="all done")
    assert ev.success is True
    assert ev.error == ""


def test_max_turns_result_surfaces_a_legible_error():
    ev = _result(subtype="error_max_turns")
    assert ev.success is False
    assert ev.error, "max-turns exhaustion must carry an error message"
    assert "error_max_turns" in ev.error


def test_explicit_error_is_preserved():
    ev = _result(subtype="error", is_error=True, result="bad model string")
    assert ev.success is False
    assert "bad model string" in ev.error


def test_build_args_max_turns_default_is_generous():
    """20 was far too low — real coding tasks need many turns."""
    args = ClaudeRuntime.build_args("do the thing")
    i = args.index("--max-turns")
    assert int(args[i + 1]) >= 200
