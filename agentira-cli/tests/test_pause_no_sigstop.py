"""Regression: pausing a run must NOT SIGSTOP the subprocess.

SIGSTOP freezes claude-code with its LLM + MCP streaming sockets open;
the remote side drops the idle connection and the run dies with
'subprocess exited with code 1' on resume. Pause must instead cleanly
terminate the process (SIGTERM) — the session_id is preserved and the
backend re-dispatches with `claude --resume`.
"""

from __future__ import annotations

import signal
from unittest import mock

from agentira_cli.daemon.core import AgentiraDaemon
from agentira_cli.state.config import DaemonConfig


def _daemon() -> AgentiraDaemon:
    return AgentiraDaemon(DaemonConfig())


def _fake_proc(pid: int = 4242):
    proc = mock.Mock()
    proc.pid = pid
    return proc


def test_pause_terminates_not_sigstops():
    """P5: pause now group-SIGTERMs via _signal_group rather than a per-
    PID proc.terminate(). Still no SIGSTOP."""
    d = _daemon()
    proc = _fake_proc()
    d._inflight["t1"] = {"proc": proc}

    with mock.patch.object(d, "_signal_group") as sg:
        d._signal_proc({"trace_id": "t1"}, "pause")
        sg.assert_called_once_with(proc, signal.SIGTERM)
    # The bug was send_signal(SIGSTOP) — must never happen.
    for call in proc.send_signal.call_args_list:
        assert call.args[0] != signal.SIGSTOP, "pause must not SIGSTOP"


def test_pause_marks_entry_paused():
    d = _daemon()
    d._inflight["t1"] = {"proc": _fake_proc()}
    d._signal_proc({"trace_id": "t1"}, "pause")
    assert d._inflight["t1"]["paused"] is True


def test_resume_is_a_noop_no_signal():
    """Resume sends NO signal — there is no stopped process to continue;
    the backend re-dispatches a fresh process instead."""
    d = _daemon()
    proc = _fake_proc()
    d._inflight["t1"] = {"proc": proc}
    d._signal_proc({"trace_id": "t1"}, "resume")
    proc.send_signal.assert_not_called()
    proc.terminate.assert_not_called()
    proc.kill.assert_not_called()


def test_pause_resolves_trace_via_run_id():
    d = _daemon()
    proc = _fake_proc()
    d._inflight["trace-x"] = {"proc": proc}
    d._run_to_trace["run-9"] = "trace-x"
    with mock.patch.object(d, "_signal_group") as sg:
        d._signal_proc({"run_id": "run-9"}, "pause")
        sg.assert_called_once_with(proc, signal.SIGTERM)


def test_pause_unknown_trace_is_safe():
    d = _daemon()
    # No inflight entry — must not raise.
    d._signal_proc({"trace_id": "nope"}, "pause")
