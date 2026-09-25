"""Loop v1 C4: nothing reports dispatched / online unless it is.

A runtime is live only when a connected daemon REGISTERED that runtime id —
a stale runtime row sharing a live daemon's id is not live. A Conductor turn
whose runtime is not live is recorded `undelivered` and nothing is sent."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.db import privileged
from backend.forge import conductor, services as forge_services
from backend.forge.models import ForgeRuntime
from backend.forge.ws_dispatch import DaemonConnection, hub
from backend.tests.test_conductor_turn_scopes import _mk_project_with_agent


@pytest.fixture(autouse=True)
def _db(pg):
    yield pg


def _fake_conn(daemon_id: str, runtime_ids: list[str]) -> DaemonConnection:
    conn = DaemonConnection.__new__(DaemonConnection)
    conn.daemon_id, conn.runtime_ids = daemon_id, runtime_ids
    return conn


def test_hub_runtime_liveness_is_per_runtime_not_per_daemon():
    hub._conns["dX"] = _fake_conn("dX", ["rt-live"])
    try:
        assert hub.is_runtime_live("rt-live")
        assert not hub.is_runtime_live("rt-stale")
    finally:
        hub._conns.pop("dX", None)


def test_stale_runtime_row_of_a_connected_daemon_reads_offline():
    live = ForgeRuntime(id="rtlive000001", daemon_id="dY", provider="claude",
                        binary_path="/b", status="online")
    stale = ForgeRuntime(id="rtstale00001", daemon_id="dY", provider="claude",
                         binary_path="/b", status="online")
    hub._conns["dY"] = _fake_conn("dY", ["rtlive000001"])
    try:
        assert forge_services._is_runtime_online(live)
        assert not forge_services._is_runtime_online(stale)
    finally:
        hub._conns.pop("dY", None)


def test_offline_conductor_runtime_records_undelivered_and_sends_nothing():
    _mk_project_with_agent("Off")
    with patch.object(conductor, "_runtime_live", return_value=True):
        conductor.get_or_create_conductor()   # bound while its daemon was up
    with patch.object(forge_services, "send_runtime_message") as send, \
         patch.object(conductor, "_runtime_live", return_value=False), privileged():
        conductor.run_planning_turn()
    send.assert_not_called()
    turn = conductor.get_recent_planning_turns(limit=1)[0]
    assert turn["status"] == "undelivered"
    assert "offline" in turn["decisions"][-1]["reason"]


def test_seeding_binds_a_live_claude_runtime_not_the_first_row(pg):
    from backend.db import SessionLocal
    from backend.models import Profile
    with SessionLocal() as db:
        # A row left by an old daemon install that no longer connects.
        db.add(ForgeRuntime(id="rtdead000001", daemon_id="dOld", provider="claude",
                            binary_path="/b", status="online"))
        db.add(ForgeRuntime(id="rtlive000002", daemon_id="dZ", provider="claude",
                            binary_path="/b", status="online"))
        db.commit()
    hub._conns["dZ"] = _fake_conn("dZ", ["rtlive000002"])
    try:
        cond = conductor.get_or_create_conductor()
        with SessionLocal() as db:
            assert db.get(Profile, cond["id"]).runtime_id == "rtlive000002"
    finally:
        hub._conns.pop("dZ", None)
