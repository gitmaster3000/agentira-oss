"""Per-project work-signal setting + scope-live endpoint (ADR 009 / AP-138 E2/E3)."""

from __future__ import annotations

import pytest

from backend import services as core_services
from backend.forge import services as forge_services, turns, live_inflight


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg.SessionLocal


def test_update_and_resolve_work_signal():
    p = core_services.create_project("P", actor="system")
    assert turns.resolve_work_signal_mode(p["id"]) == "working_tree"  # default

    core_services.update_project(p["id"], work_signal="committed")
    assert core_services.get_project(p["id"])["work_signal"] == "committed"
    assert turns.resolve_work_signal_mode(p["id"]) == "committed"


def test_invalid_work_signal_ignored():
    p = core_services.create_project("P", actor="system")
    core_services.update_project(p["id"], work_signal="garbage")
    assert core_services.get_project(p["id"])["work_signal"] == ""
    assert turns.resolve_work_signal_mode(p["id"]) == "working_tree"


def test_scope_live_reflects_mirror():
    live_inflight._by_scope.clear()
    assert forge_services.scope_live("task:abc") == {"live": False, "trace_id": ""}
    live_inflight.set_for_daemon("d1", [{"scope_key": "task:abc", "trace_id": "t9"}])
    res = forge_services.scope_live("task:abc")
    assert res["live"] is True and res["trace_id"] == "t9"
