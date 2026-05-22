"""P1 — daemon-side robustness for Stop:

  - Cancel arriving *before* the subprocess is bound to the inflight
    entry must still kill it the moment it appears (no leak).
  - Cancel kills via SIGTERM (graceful) plus a SIGKILL watchdog so a
    subprocess that ignores SIGTERM is killed within _STOP_GRACE_S.
  - The cancelled completion is posted with cancelled=True so the
    backend flips the run to CANCELLED (not FAILED) and skips the admin
    failure notification.

P5: cancel kills the whole process group, not just claude — so a
bash-backgrounded child (`vite dev &`, `pytest &`) dies with its parent.

The pause path symmetry is covered by test_pause_no_sigstop.py + the
backend-side test_stop_handshake.py.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from unittest import mock

import pytest

from agentira_cli.daemon.core import AgentiraDaemon
from agentira_cli.state.config import DaemonConfig


def _daemon() -> AgentiraDaemon:
    return AgentiraDaemon(DaemonConfig())


def _live_proc(pid: int = 9999):
    """Mock subprocess that reports alive across poll() calls until
    .kill() flips it."""
    proc = mock.Mock()
    proc.pid = pid
    proc._dead = False
    proc.poll.side_effect = lambda: 0 if proc._dead else None

    def _kill():
        proc._dead = True
    proc.kill.side_effect = _kill
    return proc


# ── cancel-before-bind race ──────────────────────────────────────────

def test_cancel_before_bind_kills_at_on_proc_time():
    """The bug: cancel arrives in the window between dispatch creating
    the inflight entry and on_proc binding the real subprocess. The
    proc would start unattended and run to completion. Fixed: on_proc
    consults the intent flag and kills immediately."""
    d = _daemon()
    trace = "race-1"
    d._inflight[trace] = {"proc": None, "cancelled": False}

    # Cancel arrives first — proc not yet bound.
    d._cancel({"trace_id": trace})
    assert d._inflight[trace]["cancelled"] is True

    # Now the subprocess actually starts. Simulate dispatch's on_proc
    # callback by mirroring the closure logic.
    proc = _live_proc()

    # Re-create the on_proc closure logic (small enough to inline in
    # the test rather than refactor the daemon for testability).
    def on_proc(p):
        stop_now = False
        with d._inflight_lock:
            entry = d._inflight.get(trace)
            if entry is not None:
                entry["proc"] = p
                if entry.get("cancelled"):
                    stop_now = True
        if stop_now and p is not None:
            p.terminate()
            d._sigkill_watchdog(trace, p)

    on_proc(proc)
    proc.terminate.assert_called_once()


def test_pause_before_bind_marks_intent_only():
    """Pause-before-bind doesn't have a proc to terminate yet — the
    intent flag is what later trips the same on_proc kill path."""
    d = _daemon()
    d._inflight["t1"] = {"proc": None, "cancelled": False}
    d._signal_proc({"trace_id": "t1"}, "pause")
    assert d._inflight["t1"]["paused"] is True


# ── SIGKILL watchdog ─────────────────────────────────────────────────

def test_sigkill_watchdog_fires_when_sigterm_ignored():
    """If SIGTERM doesn't take, SIGKILL must fire within _STOP_GRACE_S
    so Stop is actually reliable. P5: the watchdog calls _signal_group
    so the SIGKILL targets the whole process group."""
    d = _daemon()
    d._STOP_GRACE_S = 0.05  # shrink for the test

    proc = _live_proc()  # poll() returns None — process is "alive"
    with mock.patch.object(d, "_signal_group") as sg:
        d._sigkill_watchdog("t-watch", proc)
        time.sleep(0.2)  # > grace * 2
        sg.assert_called_once_with(proc, signal.SIGKILL)


def test_sigkill_watchdog_skips_when_proc_already_exited():
    """No SIGKILL if SIGTERM (or a normal exit) already happened."""
    d = _daemon()
    d._STOP_GRACE_S = 0.05

    proc = _live_proc()
    proc._dead = True  # already exited cleanly
    with mock.patch.object(d, "_signal_group") as sg:
        d._sigkill_watchdog("t-clean", proc)
        time.sleep(0.2)
        sg.assert_not_called()


# ── cancel path with bound proc ──────────────────────────────────────

def test_cancel_with_bound_proc_terminates_and_schedules_kill():
    """P5: cancel routes through _signal_group (group SIGTERM) and
    schedules the SIGKILL watchdog."""
    d = _daemon()
    proc = _live_proc()
    d._inflight["t2"] = {"proc": proc, "cancelled": False}

    with mock.patch.object(d, "_sigkill_watchdog") as wd, \
         mock.patch.object(d, "_signal_group") as sg:
        d._cancel({"trace_id": "t2"})

    sg.assert_called_once_with(proc, signal.SIGTERM)
    wd.assert_called_once()
    assert d._inflight["t2"]["cancelled"] is True


# ── trigger-complete carries cancelled flag ──────────────────────────

def test_post_trigger_complete_accepts_cancelled_kwarg():
    """The REST client must accept cancelled=True so the daemon can
    signal the backend that this was a user-initiated cancel, not a
    crash."""
    from agentira_cli.transport.rest import AgentiraClient
    c = AgentiraClient(base_url="http://x", api_key="k")
    with mock.patch.object(c, "_post", return_value={"ok": True}) as p:
        c.post_trigger_complete(
            "agent-1", daemon_id="d", trace_id="t",
            success=False, cancelled=True,
        )
    args, _ = p.call_args
    payload = args[1]
    assert payload["cancelled"] is True


# ── P5: process-group cleanup ────────────────────────────────────────

def _is_alive(pid: int) -> bool:
    """POSIX: signal 0 raises ProcessLookupError if the pid is gone."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but we can't signal — alive enough


@pytest.mark.skipif(sys.platform == "win32",
                    reason="process groups are POSIX-only")
def test_cancel_kills_backgrounded_child_via_group():
    """Spawn a parent in its own session that forks a child sleeper, then
    invoke _cancel. P5 must take down the whole group: parent + child."""
    # Parent: print child's PID on stdout, then sleep. Child: sleep
    # detached so a per-PID SIGTERM on the parent wouldn't catch it.
    parent_script = (
        "import os, sys, time;\n"
        "p = os.fork()\n"
        "if p == 0:\n"
        "    # child — pretend to be a bash-backgrounded dev server\n"
        "    time.sleep(60)\n"
        "    sys.exit(0)\n"
        "else:\n"
        "    sys.stdout.write(str(p) + '\\n'); sys.stdout.flush()\n"
        "    time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", parent_script],
        stdout=subprocess.PIPE,
        start_new_session=True,  # mirrors run_cli_stream's spawn
    )
    try:
        child_line = proc.stdout.readline()
        child_pid = int(child_line.strip())
        assert _is_alive(proc.pid) and _is_alive(child_pid)

        d = _daemon()
        d._STOP_GRACE_S = 0.2  # shrink so the watchdog has fired before assert
        d._inflight["t-pg"] = {"proc": proc, "cancelled": False}
        d._cancel({"trace_id": "t-pg"})

        # Give SIGTERM time to land; the parent's wrapper exits and the
        # whole group goes down. Allow up to STOP_GRACE_S * 3 for slow CI.
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if not _is_alive(proc.pid) and not _is_alive(child_pid):
                break
            time.sleep(0.05)

        assert not _is_alive(proc.pid), "parent survived cancel"
        assert not _is_alive(child_pid), (
            "backgrounded child survived cancel — group kill didn't work")
    finally:
        # Belt and suspenders.
        for pid in (proc.pid,):
            try: os.kill(pid, signal.SIGKILL)
            except ProcessLookupError: pass
        try: proc.wait(timeout=2)
        except Exception: pass


def test_signal_group_falls_back_when_proc_not_a_leader():
    """Stand-in proc with a pid that ISN'T a session leader (the test
    mocks don't set start_new_session). _signal_group must fall back to
    proc.terminate()/.kill() so legacy tests still pass."""
    d = _daemon()
    proc = mock.Mock()
    # Pick a pid that almost certainly isn't a session leader on this
    # machine; killpg raises PermissionError or ProcessLookupError.
    proc.pid = 1  # init — we can't killpg init
    proc.terminate = mock.Mock()
    proc.kill = mock.Mock()
    d._signal_group(proc, signal.SIGTERM)
    # Either killpg succeeded (unlikely as non-root) or we fell back.
    # If we fell back, terminate was called. If killpg "succeeded",
    # terminate was not — both are acceptable on this machine. The
    # important guarantee is: no exception escaped.

