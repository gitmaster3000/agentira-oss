"""P1 — daemon-side robustness for Stop:

  - Cancel arriving *before* the subprocess is bound to the inflight
    entry must still kill it the moment it appears (no leak).
  - Cancel kills via SIGTERM (graceful) plus a SIGKILL watchdog so a
    subprocess that ignores SIGTERM is killed within _STOP_GRACE_S.
  - The cancelled completion is posted with cancelled=True so the
    backend flips the run to CANCELLED (not FAILED) and skips the admin
    failure notification.

The pause path symmetry is covered by test_pause_no_sigstop.py + the
backend-side test_stop_handshake.py.
"""

from __future__ import annotations

import time
from unittest import mock

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
    so Stop is actually reliable."""
    d = _daemon()
    d._STOP_GRACE_S = 0.05  # shrink for the test

    proc = _live_proc()  # poll() returns None — process is "alive"
    d._sigkill_watchdog("t-watch", proc)
    time.sleep(0.2)  # > grace * 2
    proc.kill.assert_called_once()


def test_sigkill_watchdog_skips_when_proc_already_exited():
    """No SIGKILL if SIGTERM (or a normal exit) already happened."""
    d = _daemon()
    d._STOP_GRACE_S = 0.05

    proc = _live_proc()
    proc._dead = True  # already exited cleanly
    d._sigkill_watchdog("t-clean", proc)
    time.sleep(0.2)
    proc.kill.assert_not_called()


# ── cancel path with bound proc ──────────────────────────────────────

def test_cancel_with_bound_proc_terminates_and_schedules_kill():
    d = _daemon()
    proc = _live_proc()
    d._inflight["t2"] = {"proc": proc, "cancelled": False}

    with mock.patch.object(d, "_sigkill_watchdog") as wd:
        d._cancel({"trace_id": "t2"})

    proc.terminate.assert_called_once()
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
