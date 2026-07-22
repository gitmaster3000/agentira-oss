"""Regression: the finally-block log-file close must not mask an early error.

`stdout_log_f` / `stderr_log_f` are used in the finally cleanup. If they were
only bound *after* the subprocess spawned, a failure before the spawn (a bad
binary path -> FileNotFoundError from create_subprocess_exec, a build_args
error, ...) made the finally raise `UnboundLocalError: local variable
'stdout_log_f' referenced before assignment`, hiding the real cause. This bit
the codex live run. They must be bound before the try.
"""

from __future__ import annotations

import asyncio

import pytest

from agentira_cli.daemon.executor import run_cli_stream
from agentira_cli.runtimes.codex import CodexRuntime


def test_spawn_failure_surfaces_real_error_not_unbound_local(tmp_path):
    # Non-existent binary -> create_subprocess_exec raises before the log
    # files are opened. We must see that error, not UnboundLocalError.
    with pytest.raises(Exception) as ei:
        asyncio.run(run_cli_stream(
            CodexRuntime,
            str(tmp_path / "no-such-codex-binary"),
            "hi",
            stdout_log_path=str(tmp_path / "out.log"),
            stderr_log_path=str(tmp_path / "err.log"),
        ))
    assert "referenced before assignment" not in str(ei.value)
    assert isinstance(ei.value, (FileNotFoundError, OSError))
