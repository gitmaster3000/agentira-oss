"""Tests for WS keepalive + durable dispatch delivery.

AP-361 follow-up introduced an in-memory redelivery queue for triggers
dispatched while no daemon was online. AP-390 replaced that queue with a
durable outbox (DispatchIntent rows): the in-memory dict lived in a
per-process hub singleton, and finish_run — hence every workflow-driver
dispatch — executes in the flowty-mcp process, whose hub never holds the
daemon's WS socket. Those frames queued into a dict no daemon would ever
reconnect to and expired silently (prod incident 2026-07-04).

Under test, in backend/forge/ws_dispatch.py + backend/forge/dispatch_outbox.py:
1. handle_daemon_ws probes with an app-level ping and deregisters the
   daemon once WS_HEARTBEAT_TIMEOUT_S passes with no frame of any kind.
2. dispatch_trigger/dispatch_integrate write a DispatchIntent row before
   any send attempt; with no daemon in this process the row stays pending.
3. A daemon (re)connect drains pending rows for its runtimes.
4. The flowty-api sweep (deliver_pending) delivers rows written by a
   hub-less process, and fails them visibly after the TTL.
"""

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend.forge import dispatch_outbox, ws_dispatch
from backend.forge.models import DispatchIntent
from backend.forge.ws_dispatch import DaemonConnection, WsHub


class FakeWebSocket:
    """Minimal stand-in for fastapi.WebSocket: a scripted inbound queue plus
    a record of everything sent, so tests can drive handle_daemon_ws without
    a real socket."""

    def __init__(self, inbound: list):
        self._inbound = list(inbound)
        self.sent: list[dict] = []
        self.closed_code: int | None = None

    async def accept(self):
        pass

    async def receive_json(self):
        return self._next()

    async def receive_text(self):
        return json.dumps(self._next())

    def _next(self):
        if not self._inbound:
            # Block "forever" (test timeouts drive the heartbeat path).
            raise _Block()
        item = self._inbound.pop(0)
        if item is _DISCONNECT:
            from fastapi import WebSocketDisconnect
            raise WebSocketDisconnect()
        return item

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code: int = 1000):
        self.closed_code = code

    @property
    def headers(self):
        return {}

    @property
    def query_params(self):
        return {}


class _Block(Exception):
    """Raised by FakeWebSocket.receive_* when the inbound script is
    exhausted, so awaiting it never resolves within a test's timeout."""


_DISCONNECT = object()


@pytest.fixture(autouse=True)
def fast_heartbeat(monkeypatch):
    """Shrink the heartbeat interval/timeout so the deregistration test
    runs in milliseconds instead of the real 20s/45s defaults."""
    monkeypatch.setattr(ws_dispatch, "WS_HEARTBEAT_INTERVAL_S", 0.02)
    monkeypatch.setattr(ws_dispatch, "WS_HEARTBEAT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(ws_dispatch, "DISPATCH_REDELIVER_TTL_S", 0.05)


@pytest.fixture(autouse=True)
def outbox_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.forge.dispatch_outbox.SessionLocal", TestSession):
        yield TestSession


def _pending_rows(TestSession):
    with TestSession() as db:
        return db.query(DispatchIntent).filter(
            DispatchIntent.status == "pending").all()


@pytest.mark.asyncio
async def test_dispatch_queues_and_redelivers_after_silent_ws_death(outbox_db):
    """Core case: kill the WS without a clean disconnect, dispatch a
    trigger while nobody's registered, then reconnect — the trigger must
    still land instead of the run being failed instantly."""
    hub = WsHub()
    ws = FakeWebSocket(inbound=[])
    conn = DaemonConnection(ws, "daemon-1", ["rt-1"])
    await hub.connect(conn)

    # Simulate the half-open death: the daemon vanishes without the WS
    # handler's finally-block ever running disconnect().
    hub._conns.pop("daemon-1")

    dropped_calls = []

    import backend.forge.services as forge_services
    with patch.object(forge_services, "mark_dispatch_dropped",
                       lambda **kw: dropped_calls.append(kw)):
        await hub.dispatch_trigger(
            trace_id="trace-1", runtime_id="rt-1", agent_id="agent-1",
            kind="chat", prompt="hello", run_id="run-1",
        )

        # Not delivered yet (nobody online) and NOT failed yet either —
        # the frame sits durable in the outbox.
        rows = _pending_rows(outbox_db)
        assert [r.event_id for r in rows] == ["trace-1"]
        assert dropped_calls == []

        # Daemon reconnects — the queued trigger must be redelivered to
        # the new connection, not lost.
        ws2 = FakeWebSocket(inbound=[])
        conn2 = DaemonConnection(ws2, "daemon-1", ["rt-1"])
        await hub.connect(conn2)

        delivered = await asyncio.wait_for(conn2._queue.get(), timeout=1)
        assert delivered["trace_id"] == "trace-1"
        assert delivered["type"] == "trigger"
        assert _pending_rows(outbox_db) == []
        assert dropped_calls == []


@pytest.mark.asyncio
async def test_cross_process_dispatch_survives_and_api_sweep_delivers(outbox_db):
    """AP-390 core: the hub that WRITES the intent has no daemon (that's
    flowty-mcp serving finish_run) — a DIFFERENT hub with the socket (the
    flowty-api process) must deliver it on its sweep."""
    mcp_hub = WsHub()   # hub-less process: no daemon ever connects here
    await mcp_hub.dispatch_trigger(
        trace_id="trace-x", runtime_id="rt-1", agent_id="agent-1",
        kind="run_step", prompt="review this", run_id="run-x",
    )
    assert len(_pending_rows(outbox_db)) == 1

    # "flowty-api": a separate hub instance that holds the daemon socket.
    api_hub = WsHub()
    ws = FakeWebSocket(inbound=[])
    conn = DaemonConnection(ws, "daemon-1", ["rt-1"])
    # Register without connect() so the reconnect-drain path doesn't fire —
    # we're testing the sweep specifically.
    api_hub._conns["daemon-1"] = conn

    with patch.object(ws_dispatch, "hub", api_hub):
        result = await dispatch_outbox.deliver_pending()

    assert result["delivered"] == 1
    delivered = await asyncio.wait_for(conn._queue.get(), timeout=1)
    assert delivered["trace_id"] == "trace-x"
    assert _pending_rows(outbox_db) == []


@pytest.mark.asyncio
async def test_integrate_written_durably_and_swept(outbox_db):
    """An integrate dispatched with no daemon in-process must not vanish —
    it queues durably and the api sweep delivers it."""
    mcp_hub = WsHub()
    ok = await mcp_hub.dispatch_integrate(
        runtime_id="rt-1", task_id="task-1", run_id="run-1",
        source_url="https://example.com/repo.git", branch="agent/x/task/y",
    )
    assert ok is True  # queued durably ≠ dropped
    rows = _pending_rows(outbox_db)
    assert [r.kind for r in rows] == ["integrate"]

    api_hub = WsHub()
    ws = FakeWebSocket(inbound=[])
    conn = DaemonConnection(ws, "daemon-1", ["rt-1"])
    api_hub._conns["daemon-1"] = conn
    with patch.object(ws_dispatch, "hub", api_hub):
        result = await dispatch_outbox.deliver_pending()
    assert result["delivered"] == 1
    frame = await asyncio.wait_for(conn._queue.get(), timeout=1)
    assert frame["type"] == "integrate"
    assert frame["branch"] == "agent/x/task/y"
    assert _pending_rows(outbox_db) == []


@pytest.mark.asyncio
async def test_sweep_fails_intent_only_after_ttl_expires(outbox_db):
    """No daemon anywhere within the TTL: the run must be surfaced as
    failed, but only then — never instantly."""
    hub = WsHub()
    dropped_calls = []

    import backend.forge.services as forge_services
    with patch.object(forge_services, "mark_dispatch_dropped",
                       lambda **kw: dropped_calls.append(kw)):
        await hub.dispatch_trigger(
            trace_id="trace-2", runtime_id="rt-2", agent_id="agent-2",
            kind="chat", prompt="hello", run_id="run-2",
        )
        assert dropped_calls == []  # not instant

        # Sweep before the TTL: intent stays pending, nothing dropped.
        with patch.object(ws_dispatch, "hub", hub):
            monkey_ttl = patch.object(ws_dispatch, "DISPATCH_REDELIVER_TTL_S", 3600)
            with monkey_ttl:
                result = await dispatch_outbox.deliver_pending()
        assert result == {"delivered": 0, "failed": 0}
        assert len(_pending_rows(outbox_db)) == 1
        assert dropped_calls == []

        # Past the TTL (fixture set it to 0.05s): sweep fails it visibly.
        await asyncio.sleep(0.1)
        with patch.object(ws_dispatch, "hub", hub):
            result = await dispatch_outbox.deliver_pending()
        assert result["failed"] == 1
        assert dropped_calls and dropped_calls[0]["trace_id"] == "trace-2"
        assert dropped_calls[0]["run_id"] == "run-2"
        assert _pending_rows(outbox_db) == []


@pytest.mark.asyncio
async def test_intent_survives_process_death(outbox_db):
    """Redeploy simulation: the writing hub object is discarded (process
    died) — a brand-new hub in a new process still delivers the row."""
    dying_hub = WsHub()
    await dying_hub.dispatch_trigger(
        trace_id="trace-r", runtime_id="rt-1", agent_id="agent-1",
        kind="run_step", prompt="hi", run_id="run-r",
    )
    del dying_hub  # process death: all in-memory state gone

    fresh_hub = WsHub()
    ws = FakeWebSocket(inbound=[])
    conn = DaemonConnection(ws, "daemon-1", ["rt-1"])
    await fresh_hub.connect(conn)  # reconnect drain delivers from the DB

    delivered = await asyncio.wait_for(conn._queue.get(), timeout=1)
    assert delivered["trace_id"] == "trace-r"
    assert _pending_rows(outbox_db) == []


@pytest.mark.asyncio
async def test_fast_path_marks_intent_delivered(outbox_db):
    """Daemon connected to the dispatching process: send immediately, and
    the intent row records the delivery (audit trail, no pending residue)."""
    hub = WsHub()
    ws = FakeWebSocket(inbound=[])
    conn = DaemonConnection(ws, "daemon-1", ["rt-1"])
    await hub.connect(conn)

    await hub.dispatch_trigger(
        trace_id="trace-f", runtime_id="rt-1", agent_id="agent-1",
        kind="chat", prompt="hello", run_id="run-f",
    )
    delivered = await asyncio.wait_for(conn._queue.get(), timeout=1)
    assert delivered["trace_id"] == "trace-f"
    with outbox_db() as db:
        row = db.query(DispatchIntent).filter(
            DispatchIntent.event_id == "trace-f").one()
        assert row.status == "delivered"
        assert row.delivered_at is not None


@pytest.mark.asyncio
async def test_handle_daemon_ws_deregisters_half_open_connection(monkeypatch):
    """The server-side heartbeat probe must notice a half-open socket
    (recv() blocks forever, no pong ever arrives) and deregister the daemon
    within the configured timeout instead of leaving a dead entry in the
    hub forever."""
    monkeypatch.setattr(ws_dispatch, "_auth_ws_token",
                         lambda *a, **kw: {"org_id": "org-1"})
    monkeypatch.setattr(ws_dispatch, "_runtimes_in_org",
                         lambda runtime_ids, org_id: runtime_ids)

    ws = FakeWebSocket(inbound=[{"daemon_id": "daemon-x", "runtime_ids": ["rt-x"]}])
    # After the init frame, every further receive_text() blocks (half-open
    # socket) until the fixture-shrunk heartbeat timeout gives up on it.
    ws._next_orig = ws._next

    async def blocking_receive_text():
        await asyncio.sleep(3600)

    ws.receive_text = blocking_receive_text

    assert not ws_dispatch.hub.is_connected("daemon-x")
    await asyncio.wait_for(ws_dispatch.handle_daemon_ws(ws), timeout=2)

    assert not ws_dispatch.hub.is_connected("daemon-x")
    # At least one app-level ping probe should have been sent before giving up.
    assert any(f.get("type") == "ping" for f in ws.sent)
