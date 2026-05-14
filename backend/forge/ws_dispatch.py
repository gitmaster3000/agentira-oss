"""WebSocket hub for daemon ↔ server push.

Daemons connect to /api/forge/daemon/ws with their daemon_id and runtime provider list.
When a task is assigned to an agent bound to one of those runtimes, the server sends
a task_available frame so the daemon can skip waiting for the poll cycle.

Ported conceptually from multica/server/internal/daemonws/hub.go:20-200.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger("agentira.forge.ws_dispatch")

_SEND_BUF = 16          # outbound message buffer per daemon
_DEDUP_RING = 128       # event IDs to remember per daemon (deduplicate)


class DaemonConnection:
    def __init__(self, ws: "WebSocket", daemon_id: str, runtime_ids: list[str]) -> None:
        self.ws = ws
        self.daemon_id = daemon_id
        self.runtime_ids: set[str] = set(runtime_ids)
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=_SEND_BUF)
        self._seen: deque = deque(maxlen=_DEDUP_RING)

    async def send(self, event_id: str, payload: dict) -> None:
        if event_id in self._seen:
            return
        self._seen.append(event_id)
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("Send buffer full for daemon %s — dropping frame", self.daemon_id[:8])

    async def write_pump(self) -> None:
        """Drain the outbound queue into the WebSocket."""
        while True:
            msg = await self._queue.get()
            try:
                await self.ws.send_json(msg)
            except Exception as exc:
                logger.debug("WS send error for %s: %s", self.daemon_id[:8], exc)
                break


class WsHub:
    """Thread-safe (asyncio) registry of connected daemon WebSockets."""

    def __init__(self) -> None:
        self._conns: dict[str, DaemonConnection] = {}  # daemon_id → conn
        self._lock = asyncio.Lock()

    async def connect(self, conn: DaemonConnection) -> None:
        async with self._lock:
            old = self._conns.get(conn.daemon_id)
            self._conns[conn.daemon_id] = conn
        if old is not None and old is not conn:
            # Force the previous WS shut so its handler task exits and
            # doesn't later call disconnect() against the new registration.
            # The old task's finally block will check identity (see below)
            # and refuse to pop the new connection — but closing the old
            # socket ensures the old loop exits in the first place.
            try:
                await old.ws.close()
            except Exception:
                pass
        logger.info("Daemon connected: %s runtimes=%s", conn.daemon_id[:8], conn.runtime_ids)

    async def disconnect(self, daemon_id: str, expected: "DaemonConnection | None" = None) -> None:
        """Remove the daemon iff the current registration matches `expected`.

        When `expected` is given (the WS handler passes its own connection
        object), we only pop if it's still the registered one. This prevents
        an old reconnecting WS's finally-block from clobbering the new
        connection's registration — the race that made agents appear
        offline after every daemon reconnect cycle.
        """
        async with self._lock:
            current = self._conns.get(daemon_id)
            if expected is None or current is expected:
                self._conns.pop(daemon_id, None)
                stale = False
            else:
                stale = True
        if stale:
            logger.debug("Stale disconnect for %s ignored — newer WS holds the slot", daemon_id[:8])
        else:
            logger.info("Daemon disconnected: %s", daemon_id[:8])

    async def dispatch_trigger(self, *, trace_id: str, runtime_id: str, agent_id: str,
                               kind: str, prompt: str, run_id: str = "",
                               **runtime_args) -> None:
        """Send a trigger frame to the daemon that owns runtime_id.

        One frame shape for all invocations — chat, scheduled run step, future
        comments/webhooks. The daemon doesn't branch on `kind`; that field is
        purely for logging/auditing on this side.
        """
        payload = {
            "type": "trigger",
            "trace_id": trace_id,
            "runtime_id": runtime_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "kind": kind,
            "prompt": prompt,
            **runtime_args,
        }
        async with self._lock:
            targets = [c for c in self._conns.values() if runtime_id in c.runtime_ids]

        # No daemon online with this runtime — the trigger would vanish
        # silently and the run row would stay stuck in PENDING/RUNNING
        # forever. Mark the run failed (if any) and write a SYSTEM message
        # to the chat thread so the user sees what happened.
        if not targets:
            logger.warning(
                "Dispatch dropped: no daemon online for runtime=%s "
                "trace=%s kind=%s agent=%s run=%s",
                runtime_id[:8] if runtime_id else "-",
                trace_id, kind, agent_id, run_id or "-",
            )
            try:
                from backend.forge import services as _svc
                _svc.mark_dispatch_dropped(
                    agent_id=agent_id, trace_id=trace_id, run_id=run_id or None,
                )
            except Exception as exc:  # noqa: BLE001 — best-effort surface
                logger.warning("mark_dispatch_dropped failed: %s", exc)
            return

        for conn in targets:
            await conn.send(trace_id, payload)
            logger.info(
                "Dispatched trigger trace=%s kind=%s agent=%s run=%s → daemon=%s",
                trace_id, kind, agent_id, run_id or "-", conn.daemon_id[:8],
            )

    async def dispatch_signal(self, *, runtime_id: str, signal: str,
                              trace_id: str = "", run_id: str = "") -> None:
        """Generic in-flight control signal — pause / resume / etc.

        Uses signal name as the frame type so the daemon's WS client
        routes it the same way as cancel.
        """
        import uuid
        event_id = f"{signal}-{trace_id or run_id or uuid.uuid4()}"
        payload = {
            "type": signal,
            "trace_id": trace_id,
            "run_id": run_id,
            "runtime_id": runtime_id,
        }
        async with self._lock:
            targets = [c for c in self._conns.values() if runtime_id in c.runtime_ids]
        for conn in targets:
            await conn.send(event_id, payload)
            logger.info("Dispatched %s trace=%s run=%s → daemon=%s",
                        signal, trace_id or "-", run_id or "-", conn.daemon_id[:8])

    async def dispatch_cancel(self, *, runtime_id: str, trace_id: str = "",
                              run_id: str = "") -> None:
        """Send a cancel frame to whatever daemon owns runtime_id.

        The daemon resolves trace_id (or run_id → trace_id), marks the
        in-flight execution cancelled, and kills the subprocess. If
        nothing is in flight on the daemon side, the cancel is a no-op.
        """
        import uuid
        event_id = f"cancel-{trace_id or run_id or uuid.uuid4()}"
        payload = {
            "type": "cancel",
            "trace_id": trace_id,
            "run_id": run_id,
            "runtime_id": runtime_id,
        }
        async with self._lock:
            targets = [c for c in self._conns.values() if runtime_id in c.runtime_ids]
        for conn in targets:
            await conn.send(event_id, payload)
            logger.info("Dispatched cancel trace=%s run=%s → daemon=%s",
                        trace_id or "-", run_id or "-", conn.daemon_id[:8])

    def connected_daemon_ids(self) -> list[str]:
        return list(self._conns.keys())

    def is_connected(self, daemon_id: str) -> bool:
        return daemon_id in self._conns


# Singleton hub — shared across the FastAPI process
hub = WsHub()


async def handle_daemon_ws(ws: "WebSocket") -> None:
    """WebSocket handler called from the router for /api/forge/daemon/ws."""
    from fastapi import WebSocketDisconnect

    await ws.accept()

    try:
        init = await asyncio.wait_for(ws.receive_json(), timeout=10)
    except asyncio.TimeoutError:
        await ws.close(code=4008)
        return

    daemon_id = init.get("daemon_id", "")
    runtime_ids = init.get("runtime_ids", [])
    if not daemon_id:
        await ws.close(code=4003)
        return

    conn = DaemonConnection(ws, daemon_id, runtime_ids)
    await hub.connect(conn)

    pump_task = asyncio.create_task(conn.write_pump())
    try:
        while True:
            # keep-alive: read pings, ignore other messages
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        pump_task.cancel()
        # Pass our own connection object so the hub only pops the slot if
        # WE'RE the one still registered (reconnect-safe).
        await hub.disconnect(daemon_id, expected=conn)
