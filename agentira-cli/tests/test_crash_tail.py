"""_crash_tail — turns the last few stream events into human-readable
crash context, so a silent "subprocess exited with code 1" is diagnosable.
"""

from __future__ import annotations

from agentira_cli.daemon.executor import _crash_tail


def test_empty_recent_says_nothing_received():
    assert "No stream events" in _crash_tail([])


def test_renders_tool_use_and_result():
    out = _crash_tail([
        {"type": "tool_use", "tool": "Bash", "input": "python -V"},
        {"type": "tool_result", "tool": "Bash",
         "output": "command not found: python"},
    ])
    assert "Last activity before exit:" in out
    assert "tool Bash(python -V)" in out
    assert "command not found: python" in out


def test_renders_assistant_text():
    out = _crash_tail([{"type": "text", "text": "Now I'll run the tests"}])
    assert "assistant: Now I'll run the tests" in out


def test_long_output_is_truncated():
    out = _crash_tail([
        {"type": "tool_result", "tool": "Bash", "output": "x" * 5000},
    ])
    # The 200-char cap keeps a crash dump from blowing up the run row.
    assert len(out) < 400


def test_newlines_flattened():
    out = _crash_tail([{"type": "text", "text": "line one\nline two"}])
    assert "\n" in out  # the header newline
    # but the event text itself is single-line
    body = out.split("Last activity before exit:\n", 1)[1]
    assert "line one line two" in body
