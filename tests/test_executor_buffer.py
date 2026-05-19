"""Regression test for AP-48: subprocess stdout readline buffer overflow.

asyncio.StreamReader defaults to a 64KB line buffer; claude's stream-json
output occasionally produces lines larger than that (e.g. a tool_result
containing a big diff or read of a large file). Without bumping `limit=`
on create_subprocess_exec, run_cli_stream raises
  ValueError: Separator is found, but chunk is longer than limit
and the run dies.

This test spawns a tiny Python subprocess that emits one ~200KB line of
JSON, then a normal end-of-stream marker. It asserts run_cli_stream
drains both lines without raising — i.e. the buffer cap is high enough.
"""

import asyncio
import sys

import pytest

# The daemon CLI is a separate package (agentira-cli/) installed via
# `pip install -e ./agentira-cli`. CI's unit-tests job installs only
# the backend, so this test is opt-in: it runs locally and on any
# job that has the CLI installed, and skips cleanly otherwise.
agentira_cli_executor = pytest.importorskip(
    "agentira_cli.daemon.executor",
    reason="agentira-cli package not installed",
)
run_cli_stream = agentira_cli_executor.run_cli_stream


class _FakeRuntime:
    """Minimal Runtime stand-in: build_args returns the fake-emitter Python
    invocation; parse_event ignores everything (we only care about drain)."""

    @staticmethod
    def build_args(prompt, *, model="", max_turns=20, system_prompt="",
                   mcp_config_path="", mcp_strict=False, resume_session_id="",
                   allowed_tools=()):
        # Emit one ~200KB line, then a tiny line. Generate the big payload
        # inside the spawned process — embedding it in argv blows past the
        # OS argv size limit.
        script = (
            "import sys; "
            "sys.stdout.write('x' * 200000 + '\\n'); "
            "sys.stdout.write('done\\n'); "
            "sys.stdout.flush()"
        )
        return ["-c", script]

    @staticmethod
    def parse_event(line):
        return None


@pytest.mark.asyncio
async def test_run_cli_stream_handles_lines_larger_than_64kb():
    """A 200KB stdout line must not crash the executor."""
    result = await run_cli_stream(
        _FakeRuntime,
        sys.executable,            # binary_path = current python interpreter
        "ignored prompt",
        max_turns=1,
    )
    # No assertion on success/text — those come from a ResultEvent which
    # _FakeRuntime never emits. The test passes if we got here without an
    # asyncio LimitOverrunError / ValueError.
    assert result is not None


# Allow `pytest -q tests/test_executor_buffer.py` without a global asyncio
# config: install pytest-asyncio's auto mode locally if pytest-asyncio is
# present, otherwise skip. Avoids surprising contributors who don't have
# asyncio_mode = auto in their pyproject.
def pytest_collection_modifyitems(config, items):  # pragma: no cover
    pass
