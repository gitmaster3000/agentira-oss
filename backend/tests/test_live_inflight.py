"""Backend live-turn mirror (ADR 009 / AP-135 B4).

The daemon reports its live turns on each heartbeat; the backend keeps the
latest snapshot per daemon so stop-by-scope / always-on-Stop survive a
backend restart without the in-process _TRACE_SCOPE map.
"""

from __future__ import annotations

from backend.forge import live_inflight


def _reset():
    live_inflight._by_scope.clear()


def test_set_and_lookup():
    _reset()
    live_inflight.set_for_daemon("d1", [
        {"scope_key": "task:abc", "trace_id": "t1", "run_id": "r1", "pid": 10},
    ])
    assert live_inflight.lookup_trace("task:abc") == "t1"
    assert live_inflight.is_live("task:abc") is True
    assert live_inflight.is_live("task:other") is False


def test_heartbeat_snapshot_drops_finished_turns():
    _reset()
    live_inflight.set_for_daemon("d1", [
        {"scope_key": "task:a", "trace_id": "t1"},
        {"scope_key": "task:b", "trace_id": "t2"},
    ])
    # next heartbeat only reports task:a — task:b finished and must drop
    live_inflight.set_for_daemon("d1", [
        {"scope_key": "task:a", "trace_id": "t1"},
    ])
    assert live_inflight.is_live("task:a") is True
    assert live_inflight.is_live("task:b") is False


def test_one_daemon_does_not_clobber_another():
    _reset()
    live_inflight.set_for_daemon("d1", [{"scope_key": "task:a", "trace_id": "t1"}])
    live_inflight.set_for_daemon("d2", [{"scope_key": "task:b", "trace_id": "t2"}])
    # d2's heartbeat must not wipe d1's entry
    assert live_inflight.lookup_trace("task:a") == "t1"
    assert live_inflight.lookup_trace("task:b") == "t2"
    # d1 reporting empty drops only its own
    live_inflight.set_for_daemon("d1", [])
    assert live_inflight.is_live("task:a") is False
    assert live_inflight.is_live("task:b") is True


def test_stale_entries_age_out():
    _reset()
    live_inflight.set_for_daemon("d1", [{"scope_key": "task:a", "trace_id": "t1"}])
    # max_age_s=0 forces the just-written entry to read as stale
    assert live_inflight.lookup_trace("task:a", max_age_s=0) == ""
    assert live_inflight.is_live("task:a", max_age_s=0) is False
