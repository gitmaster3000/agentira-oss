"""Durable in-flight registry + reaper + stop-by-scope (ADR 009 / AP-135).

These guard the zombie fix: a chat/run turn must be findable and killable
from disk even after the daemon (or backend) restarts, and a fresh daemon
must reap whatever a prior instance left running.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from agentira_cli.daemon import inflight


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    # inflight stores under ~/.agentira/inflight — point HOME at a tmp dir.
    monkeypatch.setenv("HOME", str(tmp_path))
    yield


def _spawn_sleeper():
    """A real, group-leader child we can assert gets killed."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )


def test_record_list_clear_roundtrip():
    inflight.record(scope_key="task:abc", trace_id="t1", run_id="r1",
                    pid=99999, daemon_id="d1")
    live = inflight.list_live()
    assert len(live) == 1
    assert live[0]["scope_key"] == "task:abc"
    assert live[0]["trace_id"] == "t1"
    inflight.clear(scope_key="task:abc", trace_id="t1")
    assert inflight.list_live() == []


def test_clear_respects_trace_ownership():
    """A late-finishing turn must not clear a newer turn that took the scope."""
    inflight.record(scope_key="task:abc", trace_id="t-old", run_id="",
                    pid=1, daemon_id="d1")
    inflight.record(scope_key="task:abc", trace_id="t-new", run_id="",
                    pid=2, daemon_id="d1")  # overwrites — one live turn per scope
    inflight.clear(scope_key="task:abc", trace_id="t-old")  # stale clear
    live = inflight.list_live()
    assert len(live) == 1 and live[0]["trace_id"] == "t-new"


def test_reap_kills_live_orphan_and_clears():
    proc = _spawn_sleeper()
    try:
        inflight.record(scope_key="task:zzz", trace_id="t1", run_id="r1",
                        pid=proc.pid, daemon_id="prior-daemon")
        reaped = inflight.reap_orphans(daemon_id="fresh-daemon")
        assert any(e["pid"] == proc.pid and e["reaped"] == "killed" for e in reaped)
        # process group SIGTERM/SIGKILL should land within the grace window
        for _ in range(30):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert proc.poll() is not None, "orphan was not killed"
        assert inflight.list_live() == [], "registry not cleared after reap"
    finally:
        if proc.poll() is None:
            proc.kill()


def test_reap_drops_dead_record():
    inflight.record(scope_key="task:dead", trace_id="t1", run_id="",
                    pid=2_000_000_000, daemon_id="prior")  # pid that isn't alive
    reaped = inflight.reap_orphans(daemon_id="fresh")
    assert reaped and reaped[0]["reaped"] == "stale"
    assert inflight.list_live() == []


def test_cancel_scope_kills_live_and_returns_true():
    proc = _spawn_sleeper()
    try:
        inflight.record(scope_key="task:stopme", trace_id="t1", run_id="",
                        pid=proc.pid, daemon_id="d1")
        assert inflight.cancel_scope("task:stopme") is True
        for _ in range(30):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert proc.poll() is not None
        assert inflight.list_live() == []
    finally:
        if proc.poll() is None:
            proc.kill()


def test_cancel_scope_unknown_returns_false():
    assert inflight.cancel_scope("task:nope") is False
