"""Tests for the AP-361 follow-up: WS keepalive + dispatch redelivery.

Incident: a redeployed proxy left a daemon's WS half-open (TCP alive,
frames stopped) — the server never noticed via ordinary recv(), so it kept
routing dispatches to a dead connection until the run failed with "Daemon
offline at dispatch" even though the daemon was demonstrably alive.

Fix under test, both in backend/forge/ws_dispatch.py:
1. handle_daemon_ws probes with an app-level ping and deregisters the
   daemon once WS_HEARTBEAT_TIMEOUT_S passes with no frame of any kind.
2. WsHub.dispatch_trigger no longer fails a run instantly when no daemon
   is online for a runtime — it queues the trigger and redelivers it on
   the runtime's next registration, only failing after the TTL.
"""

import asyncio

import pytest

from backend.forge import ws_dispatch
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
        import json
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


async def _never_resolves(*_a, **_kw):
    await asyncio.sleep(3600)


@pytest.fixture(autouse=True)
def fast_heartbeat(monkeypatch):
    """Shrink the heartbeat interval/timeout so the deregistration test
    runs in milliseconds instead of the real 20s/45s defaults."""
    monkeypatch.setattr(ws_dispatch, "WS_HEARTBEAT_INTERVAL_S", 0.02)
    monkeypatch.setattr(ws_dispatch, "WS_HEARTBEAT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(ws_dispatch, "DISPATCH_REDELIVER_TTL_S", 0.05)


@pytest.mark.asyncio
async def test_dispatch_queues_and_redelivers_after_silent_ws_death():
    """Core DoD case: kill the WS without a clean disconnect, dispatch a
    trigger while nobody's registered, then reconnect — the trigger must
    still land instead of the run being failed instantly."""
    hub = WsHub()
    ws = FakeWebSocket(inbound=[])
    conn = DaemonConnection(ws, "daemon-1", ["rt-1"])
    await hub.connect(conn)

    # Simulate the half-open death: the daemon vanishes without the WS
    # handler's finally-block ever running disconnect() (that's exactly
    # what happened in the incident — no disconnect, no reconnect logged).
    hub._conns.pop("daemon-1")

    dropped_calls = []

    import backend.forge.services as forge_services
    from unittest.mock import patch
    with patch.object(forge_services, "mark_dispatch_dropped",
                       lambda **kw: dropped_calls.append(kw)):
        await hub.dispatch_trigger(
            trace_id="trace-1", runtime_id="rt-1", agent_id="agent-1",
            kind="chat", prompt="hello", run_id="run-1",
        )

        # Not delivered yet (nobody online) and NOT failed yet either.
        assert "rt-1" in hub._pending
        assert dropped_calls == []

        # Daemon reconnects before the TTL — the queued trigger must be
        # redelivered to the new connection, not lost.
        ws2 = FakeWebSocket(inbound=[])
        conn2 = DaemonConnection(ws2, "daemon-1", ["rt-1"])
        await hub.connect(conn2)

        delivered = await asyncio.wait_for(conn2._queue.get(), timeout=1)
        assert delivered["trace_id"] == "trace-1"
        assert delivered["type"] == "trigger"
        assert "rt-1" not in hub._pending

        # Give the TTL watchdog a chance to fire; since redelivery already
        # removed the entry it must be a no-op.
        await asyncio.sleep(0.15)
        assert dropped_calls == []


@pytest.mark.asyncio
async def test_dispatch_marked_dropped_only_after_ttl_expires():
    """No reconnect within the TTL: the run must be surfaced as failed,
    but only then — never instantly."""
    hub = WsHub()
    dropped_calls = []

    import backend.forge.services as forge_services
    from unittest.mock import patch
    with patch.object(forge_services, "mark_dispatch_dropped",
                       lambda **kw: dropped_calls.append(kw)):
        await hub.dispatch_trigger(
            trace_id="trace-2", runtime_id="rt-2", agent_id="agent-2",
            kind="chat", prompt="hello", run_id="run-2",
        )
        assert dropped_calls == []  # not instant

        await asyncio.sleep(0.2)  # past the 0.05s test TTL
        assert len(dropped_calls) == 1
        assert dropped_calls[0]["trace_id"] == "trace-2"
        assert dropped_calls[0]["run_id"] == "run-2"
        assert "rt-2" not in hub._pending


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
