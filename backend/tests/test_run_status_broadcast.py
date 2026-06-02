"""P4: WS run-status push.

Every Run.status transition should fan out a `run_status` frame to
browser WS subscribers via `client_hub.broadcast_run_status`. The
subscribe-side is exercised in an integration test below; the
fan-out semantics are exercised at the unit level so the test runs
without a real WebSocket.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    ForgeRuntime, Run, RunStatus, RuntimeStatus,
)
from backend.forge.ws_dispatch import ClientHub, client_hub
from backend.models import Profile, Role


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        db.add(Profile(name="admin", role_id=admin_role.id, password_hash=""))
        db.commit()
        db.close()
        yield TestSession


# ── ClientHub fan-out ────────────────────────────────────────────────
#
# Driven via asyncio.run from sync pytest functions — keeps the suite free
# of a pytest-asyncio plugin dependency (declared in dev deps but not
# always installed in the runtime image).

def test_client_hub_delivers_to_subscriber():
    async def _body():
        hub = ClientHub()

        class _FakeWS:
            pass
        ws = _FakeWS()
        q = await hub.subscribe("run-A", ws)
        await hub._fanout("run-A", {"type": "run_status", "run_id": "run-A",
                                    "status": "paused"})
        msg = await asyncio.wait_for(q.get(), 0.5)
        assert msg["status"] == "paused"
        assert msg["run_id"] == "run-A"
    asyncio.run(_body())


def test_client_hub_skips_other_runs():
    """A subscriber on run A must NOT see updates for run B."""
    async def _body():
        hub = ClientHub()

        class _FakeWS:
            pass
        ws_a = _FakeWS()
        q_a = await hub.subscribe("run-A", ws_a)
        await hub._fanout("run-B", {"type": "run_status", "run_id": "run-B",
                                    "status": "paused"})
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q_a.get(), 0.1)
    asyncio.run(_body())


def test_client_hub_unsubscribe_removes_listener():
    async def _body():
        hub = ClientHub()

        class _FakeWS:
            pass
        ws = _FakeWS()
        q = await hub.subscribe("run-X", ws)
        await hub.unsubscribe("run-X", ws)
        await hub._fanout("run-X", {"type": "run_status", "status": "running"})
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q.get(), 0.1)
    asyncio.run(_body())


# ── broadcast_run_status from a sync caller ──────────────────────────

def test_broadcast_from_sync_caller_lands_in_queue():
    """Services.py calls broadcast_run_status from synchronous code.
    The hub must hop onto the loop and deliver."""
    async def _body():
        class _FakeWS:
            pass
        ws = _FakeWS()
        q = await client_hub.subscribe("sync-run", ws)
        try:
            client_hub.broadcast_run_status("sync-run", "pausing")
            msg = await asyncio.wait_for(q.get(), 0.5)
            assert msg == {"type": "run_status", "run_id": "sync-run",
                           "status": "pausing", "outcome": None}
        finally:
            await client_hub.unsubscribe("sync-run", ws)
    asyncio.run(_body())


# ── transitions fire broadcasts ──────────────────────────────────────

def _setup(TestSession) -> dict:
    db = TestSession()
    from datetime import datetime, timezone
    rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                      status=RuntimeStatus.ONLINE,
                      last_heartbeat=datetime.now(timezone.utc))
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "T", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(
        agent_id=agent["id"], task_id=task["id"], project_id=project["id"],
    )
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run["id"]).first()
        r.status = RunStatus.RUNNING
        db.commit()
    return {"run_id": run["id"], "agent_id": agent["id"]}


def test_pause_run_emits_broadcast(test_db, monkeypatch):
    """pause_run must call _broadcast_status with the new PAUSING state."""
    s = _setup(test_db)
    calls = []
    monkeypatch.setattr(
        forge_services, "_broadcast_status",
        lambda rid, status, outcome=None: calls.append((rid, status, outcome)),
    )
    forge_services.pause_run(s["run_id"])
    assert any(rid == s["run_id"] and status == RunStatus.PAUSING
               for rid, status, _ in calls), calls


def test_cancel_run_emits_broadcast(test_db, monkeypatch):
    s = _setup(test_db)
    calls = []
    monkeypatch.setattr(
        forge_services, "_broadcast_status",
        lambda rid, status, outcome=None: calls.append((rid, status, outcome)),
    )
    forge_services.cancel_run(s["run_id"])
    assert any(rid == s["run_id"] and status == RunStatus.CANCELLING
               for rid, status, _ in calls), calls


def test_complete_trigger_cancelled_emits_terminal_broadcast(test_db,
                                                             monkeypatch):
    s = _setup(test_db)
    forge_services.cancel_run(s["run_id"])
    calls = []
    monkeypatch.setattr(
        forge_services, "_broadcast_status",
        lambda rid, status, outcome=None: calls.append((rid, status, outcome)),
    )
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t", run_id=s["run_id"],
        success=False, error="Cancelled by user.", cancelled=True,
    )
    assert any(rid == s["run_id"] and status == RunStatus.CANCELLED
               for rid, status, _ in calls), calls


def test_complete_trigger_paused_emits_terminal_broadcast(test_db,
                                                          monkeypatch):
    s = _setup(test_db)
    forge_services.pause_run(s["run_id"])
    calls = []
    monkeypatch.setattr(
        forge_services, "_broadcast_status",
        lambda rid, status, outcome=None: calls.append((rid, status, outcome)),
    )
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t", run_id=s["run_id"],
        success=False, paused=True, session_id="sess-x",
    )
    assert any(rid == s["run_id"] and status == RunStatus.PAUSED
               for rid, status, _ in calls), calls
