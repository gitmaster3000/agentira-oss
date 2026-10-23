"""A runtime whose daemon stopped heartbeating reads offline with a plain
reason — so a signed-out daemon is visible instead of silent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.forge import services
from backend.forge.models import ForgeRuntime


def _register(pg) -> str:
    services.register_runtimes("d-1", "Ali's Mac", [{
        "provider": "claude", "binary_path": "/usr/bin/claude"}])
    with pg.SessionLocal() as db:
        return db.query(ForgeRuntime).one().id


def _set_heartbeat(pg, rid: str, ago: timedelta) -> None:
    with pg.SessionLocal() as db:
        db.get(ForgeRuntime, rid).last_heartbeat = datetime.now(timezone.utc) - ago
        db.commit()


def test_silent_for_over_five_minutes_explains_signed_out(pg):
    rid = _register(pg)
    _set_heartbeat(pg, rid, timedelta(minutes=12))
    [rt] = services.list_runtimes()
    assert rt["status"] == "offline"
    assert "12 minutes" in rt["offline_reason"]
    assert "Ali's Mac" in rt["offline_reason"]
    assert "agentira daemon login" in rt["offline_reason"]


def test_recently_seen_offline_runtime_is_just_reconnecting(pg):
    rid = _register(pg)
    _set_heartbeat(pg, rid, timedelta(minutes=1))
    [rt] = services.list_runtimes()
    assert rt["status"] == "offline"
    assert "login" not in rt["offline_reason"]


def test_online_runtime_has_no_reason(pg, monkeypatch):
    _register(pg)
    monkeypatch.setattr(services, "_is_runtime_online", lambda rt: True)
    [rt] = services.list_runtimes()
    assert rt["status"] == "online" and rt["offline_reason"] is None
