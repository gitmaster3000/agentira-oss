"""Regression tests for AP-69: surface subprocess failures instead of silent completes.

Three layered bugs were stacked and silently swallowing claude-code errors:
1. --input-format stream-json made -p a no-op and claude exited 0 with no output.
2. parse_stream_line treated subtype="success" as success even when is_error=true.
3. executor.run_cli_stream didn't track whether a ResultEvent ever arrived and
   only read stderr conditionally, so a clean-exit-with-no-frame looked successful.

These tests pin the contracts those fixes introduced. Skipped when agentira-cli
isn't installed (CI's unit-tests job).
"""

import asyncio
import sys

import pytest

agentira_cli_executor = pytest.importorskip(
    "agentira_cli.daemon.executor",
    reason="agentira-cli package not installed",
)
run_cli_stream = agentira_cli_executor.run_cli_stream
parse_stream_line = pytest.importorskip("agentira_cli.runtimes.claude").parse_stream_line


class _ScriptedRuntime:
    """Runtime stand-in that runs an inline Python script and parses claude
    stream-json. Lets each test drive the exact bytes claude would emit."""

    def __init__(self, script: str):
        self._script = script

    def build_args(self, prompt, *, model="", max_turns=20, system_prompt="",
                   mcp_config_path="", mcp_strict=False, resume_session_id="",
                   allowed_tools=()):
        return ["-c", self._script]

    @staticmethod
    def parse_event(line):
        return parse_stream_line(line)


def _run(script: str):
    runtime = _ScriptedRuntime(script)
    return asyncio.run(run_cli_stream(runtime, sys.executable, "ignored"))


def test_clean_exit_no_result_frame_reports_failure():
    """Smoking gun for AP-69: subprocess exits 0 with no stream-json on stdout.
    Before the fix, this looked like silent success."""
    script = (
        "import sys; "
        "sys.stderr.write('There is an issue with the selected model.'); "
        "sys.exit(0)"
    )
    result = _run(script)
    assert result.success is False
    assert "issue with the selected model" in result.error
    assert result.text == ""


def test_nonzero_exit_captures_stderr():
    script = (
        "import sys; "
        "sys.stderr.write('boom: something is wrong\\n'); "
        "sys.exit(7)"
    )
    result = _run(script)
    assert result.success is False
    assert "boom" in result.error
    assert "exited with code 7" not in result.error  # stderr wins over generic msg


def test_nonzero_exit_with_no_stderr_falls_back_to_returncode_msg():
    script = "import sys; sys.exit(13)"
    result = _run(script)
    assert result.success is False
    assert "13" in result.error  # generic "subprocess exited with code 13"


def test_result_with_is_error_true_is_treated_as_failure():
    """claude-code emits subtype='success' even when the run failed,
    with a separate is_error flag and the message in `result`. Our parser
    has to honor is_error."""
    import json
    msg = json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "result": "There's an issue with the selected model (claude-sonnet-4-7).",
        "usage": {"input_tokens": 0, "output_tokens": 0},
    })
    event = parse_stream_line(msg)
    assert event is not None
    assert event.success is False
    assert "claude-sonnet-4-7" in event.error
    assert event.text == ""  # error message must NOT be surfaced as assistant text


def test_result_without_is_error_is_normal_success():
    import json
    msg = json.dumps({
        "type": "result",
        "subtype": "success",
        "result": "Hello!",
        "usage": {"input_tokens": 5, "output_tokens": 2},
    })
    event = parse_stream_line(msg)
    assert event.success is True
    assert event.text == "Hello!"
    assert event.error == ""
    assert event.input_tokens == 5
    assert event.output_tokens == 2


def test_happy_path_with_result_frame_marks_success():
    """Sanity: a subprocess that emits a proper success result frame
    should be reported as success."""
    script = (
        "import sys; "
        "sys.stdout.write('"
        '{\\"type\\":\\"result\\",\\"subtype\\":\\"success\\",'
        '\\"is_error\\":false,\\"result\\":\\"OK\\",'
        '\\"usage\\":{\\"input_tokens\\":1,\\"output_tokens\\":1}}\\n'
        "'); "
        "sys.exit(0)"
    )
    result = _run(script)
    assert result.success is True
    assert result.text == "OK"
    assert result.error == ""
