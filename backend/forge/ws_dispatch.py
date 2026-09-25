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
import os
import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger("agentira.forge.ws_dispatch")

_SEND_BUF = 16          # outbound message buffer per daemon
_DEDUP_RING = 128       # event IDs to remember per daemon (deduplicate)

# AP-361 follow-up: a redeployed-but-idle daemon WS can go half-open — the
# TCP socket looks alive to both sides but frames never arrive. Neither side
# notices via ordinary recv() until something actually tries to write, so we
# probe with an app-level ping and close/deregister if no frame (data or
# pong) has been seen within the timeout. Config, not hardcoded, per incident
# follow-up.
WS_HEARTBEAT_INTERVAL_S = float(os.environ.get("FORGE_WS_HEARTBEAT_INTERVAL_S", "20"))
WS_HEARTBEAT_TIMEOUT_S = float(os.environ.get("FORGE_WS_HEARTBEAT_TIMEOUT_S", "45"))

# How long a trigger with no daemon online waits in the redelivery queue
# before the run is failed. Matches the daemon's reconnect backoff ceiling
# with headroom (see _RECONNECT_DELAYS in agentira_cli/daemon/ws_client.py).
DISPATCH_REDELIVER_TTL_S = float(os.environ.get("FORGE_DISPATCH_REDELIVER_TTL_S", "300"))


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
        await self._deliver_pending(conn)

    async def _deliver_pending(self, conn: DaemonConnection) -> None:
        """Flush any frames queued in the durable outbox (AP-390) while no
        daemon owning one of `conn`'s runtimes was online. The outbox rows
        are written by dispatch_* in whatever process handled the trigger;
        this drain plus the flowty-api sweep are the delivery paths."""
        from backend.forge import dispatch_outbox as outbox
        for v in outbox.pending_for_runtimes(conn.runtime_ids):
            await conn.send(v["event_id"], v["payload"])
            outbox.mark_delivered(v["id"])
            logger.info("Redelivered queued %s %s → daemon=%s",
                        v["kind"], v["event_id"], conn.daemon_id[:8])

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
        # AP-390: persist the frame BEFORE any send attempt. This process's
        # hub may not hold the daemon's socket at all (finish_run served by
        # the flowty-mcp service, a redeploy window, a second replica) — the
        # row is what guarantees delivery: the flowty-api sweep or the
        # daemon's next WS registration sends it. TTL expiry with no daemon
        # surfaces the drop (dispatch_outbox._expire_stale).
        from backend.forge import dispatch_outbox as outbox
        intent_id = outbox.write_intent(
            kind="trigger", event_id=trace_id, runtime_id=runtime_id,
            payload=payload, agent_id=agent_id, run_id=run_id,
        )

        async with self._lock:
            targets = [c for c in self._conns.values() if runtime_id in c.runtime_ids]

        if not targets:
            logger.warning(
                "Dispatch queued in outbox: no daemon online in this process "
                "for runtime=%s trace=%s kind=%s agent=%s run=%s intent=%s ttl=%ss",
                runtime_id[:8] if runtime_id else "-",
                trace_id, kind, agent_id, run_id or "-",
                intent_id or "WRITE-FAILED", DISPATCH_REDELIVER_TTL_S,
            )
            if intent_id is None:
                # DB down AND no daemon: nothing can carry the frame — fail
                # loudly now instead of hanging the run forever.
                try:
                    from backend.forge import services as _svc
                    _svc.mark_dispatch_dropped(
                        agent_id=agent_id, trace_id=trace_id, run_id=run_id or None)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("mark_dispatch_dropped failed: %s", exc)
            return

        for conn in targets:
            await conn.send(trace_id, payload)
            logger.info(
                "Dispatched trigger trace=%s kind=%s agent=%s run=%s → daemon=%s",
                trace_id, kind, agent_id, run_id or "-", conn.daemon_id[:8],
            )
        outbox.mark_delivered(intent_id)

    async def dispatch_signal(self, *, runtime_id: str, signal: str,
                              trace_id: str = "", run_id: str = "",
                              scope_key: str = "") -> None:
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
            # ADR 009 / B6: scope lets the daemon resolve the live turn even
            # when the trace mapping was lost (backend restart).
            "scope_key": scope_key,
        }
        async with self._lock:
            targets = [c for c in self._conns.values() if runtime_id in c.runtime_ids]
        for conn in targets:
            await conn.send(event_id, payload)
            logger.info("Dispatched %s trace=%s run=%s → daemon=%s",
                        signal, trace_id or "-", run_id or "-", conn.daemon_id[:8])

    async def dispatch_integrate(self, *, runtime_id: str, task_id: str,
                                 run_id: str = "", source_url: str,
                                 branch: str, target_branch: str,
                                 push: bool = True, verify_cmd: str = "",
                                 verify_timeout_s: int = 1800) -> bool:
        """Workflow slice 2: ask the daemon owning runtime_id to merge an
        approved task branch into the target branch in its shared clone.
        Returns False when no daemon is online (caller surfaces the miss
        instead of letting the integration vanish silently)."""
        import uuid
        event_id = f"integrate-{task_id or uuid.uuid4()}"
        payload = {
            "type": "integrate",
            "task_id": task_id,
            "run_id": run_id,
            "runtime_id": runtime_id,
            "source_url": source_url,
            "branch": branch,
            "target_branch": target_branch,
            "push": push,
            # Loop v1 C6: run on the merged code before pushing.
            "verify_cmd": verify_cmd,
            "verify_timeout_s": verify_timeout_s,
        }
        # AP-390: durable outbox — an integrate triggered from finish_run
        # lands in the flowty-mcp process, whose hub never has the daemon.
        # The row keeps the merge alive until a process with the socket
        # (flowty-api sweep / daemon reconnect drain) delivers it.
        from backend.forge import dispatch_outbox as outbox
        intent_id = outbox.write_intent(
            kind="integrate", event_id=event_id, runtime_id=runtime_id,
            payload=payload, run_id=run_id, task_id=task_id,
        )
        async with self._lock:
            targets = [c for c in self._conns.values() if runtime_id in c.runtime_ids]
        if not targets:
            logger.warning(
                "Integrate queued in outbox: no daemon online in this process "
                "for runtime=%s task=%s intent=%s",
                runtime_id[:8] if runtime_id else "-", task_id,
                intent_id or "WRITE-FAILED")
            return intent_id is not None
        for conn in targets:
            await conn.send(event_id, payload)
            logger.info("Dispatched integrate task=%s branch=%s → daemon=%s",
                        task_id, branch, conn.daemon_id[:8])
        outbox.mark_delivered(intent_id)
        return True

    async def dispatch_deploy(self, *, runtime_id: str, payload: dict) -> bool:
        """Local Docker deploy: hand a `deploy` frame (deploy / teardown /
        status / logs) to the daemon owning runtime_id. The daemon reports back
        on /daemon/deploy-result. Durable like integrate — queued in the outbox
        until a process holding the daemon's socket delivers it."""
        event_id = payload["event_id"]
        from backend.forge import dispatch_outbox as outbox
        intent_id = outbox.write_intent(
            kind="deploy", event_id=event_id, runtime_id=runtime_id,
            payload=payload)
        async with self._lock:
            targets = [c for c in self._conns.values() if runtime_id in c.runtime_ids]
        if not targets:
            logger.warning(
                "Deploy queued in outbox: no daemon online in this process "
                "for runtime=%s action=%s intent=%s",
                runtime_id[:8] if runtime_id else "-", payload.get("action"),
                intent_id or "WRITE-FAILED")
            return intent_id is not None
        for conn in targets:
            await conn.send(event_id, payload)
            logger.info("Dispatched deploy action=%s → daemon=%s",
                        payload.get("action"), conn.daemon_id[:8])
        outbox.mark_delivered(intent_id)
        return True

    async def dispatch_cancel(self, *, runtime_id: str, trace_id: str = "",
                              run_id: str = "", scope_key: str = "") -> None:
        """Send a cancel frame to whatever daemon owns runtime_id.

        The daemon resolves trace_id (or run_id → trace_id, or scope_key →
        trace_id), marks the in-flight execution cancelled, and kills the
        subprocess. If nothing is in flight on the daemon side, the cancel
        falls back to the daemon's durable registry before becoming a no-op.
        """
        import uuid
        event_id = f"cancel-{trace_id or run_id or scope_key or uuid.uuid4()}"
        payload = {
            "type": "cancel",
            "trace_id": trace_id,
            "run_id": run_id,
            "runtime_id": runtime_id,
            # ADR 009 / B6: stop-by-scope — survives a lost trace mapping.
            "scope_key": scope_key,
        }
        async with self._lock:
            targets = [c for c in self._conns.values() if runtime_id in c.runtime_ids]
        if not targets:
            # AP-390: a cancel issued from a hub-less process (or a redeploy
            # window) still has to reach the daemon — queue it durably; the
            # flowty-api sweep or the reconnect drain carries it.
            from backend.forge import dispatch_outbox as outbox
            intent_id = outbox.write_intent(
                kind="cancel", event_id=event_id, runtime_id=runtime_id,
                payload=payload, run_id=run_id)
            logger.warning(
                "Cancel queued in outbox: no daemon online in this process "
                "for runtime=%s run=%s intent=%s",
                runtime_id[:8] if runtime_id else "-", run_id or "-",
                intent_id or "WRITE-FAILED")
            return
        for conn in targets:
            await conn.send(event_id, payload)
            logger.info("Dispatched cancel trace=%s run=%s → daemon=%s",
                        trace_id or "-", run_id or "-", conn.daemon_id[:8])

    def connected_daemon_ids(self) -> list[str]:
        return list(self._conns.keys())

    def is_connected(self, daemon_id: str) -> bool:
        return daemon_id in self._conns

    def is_runtime_live(self, runtime_id: str) -> bool:
        """True only if a connected daemon REGISTERED this runtime. A stale
        runtime row that shares a live daemon's id is not live (Loop v1 C4)."""
        return any(runtime_id in (c.runtime_ids or []) for c in self._conns.values())


# Singleton hub — shared across the FastAPI process
hub = WsHub()


# ── P4: client-side WS hub for browser run-status subscribers ─────────────
#
# Daemons own the daemon `hub` above. Browsers connecting to RunDetail
# subscribe here for live status updates so they don't have to wait for
# the 5s poll. One subscriber map per run_id; broadcast on every Run
# status transition the backend writes.


class ClientHub:
    """Per-run subscriber registry for browser WS clients (RunDetail).

    Lightweight: no dedup ring, no daemon_id, no runtime routing — just
    "anyone watching this run, here's an update."
    """

    def __init__(self) -> None:
        # run_id → list of (WebSocket, asyncio.Queue) tuples
        self._subs: dict[str, list[tuple]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, run_id: str, ws: "WebSocket") -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_SEND_BUF)
        async with self._lock:
            self._subs.setdefault(run_id, []).append((ws, q))
        return q

    async def unsubscribe(self, run_id: str, ws: "WebSocket") -> None:
        async with self._lock:
            arr = self._subs.get(run_id)
            if not arr:
                return
            self._subs[run_id] = [t for t in arr if t[0] is not ws]
            if not self._subs[run_id]:
                self._subs.pop(run_id, None)

    def broadcast_run_status(self, run_id: str, status: str,
                             outcome: str | None = None) -> None:
        """Schedule a broadcast to every subscriber of `run_id`. Safe to
        call from sync code (services.py / scheduler ticks) — we hop onto
        the running asyncio loop via `asyncio.run_coroutine_threadsafe`."""
        if not run_id:
            return
        payload = {"type": "run_status", "run_id": run_id,
                   "status": status, "outcome": outcome}
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return  # no loop here — caller is fully sync; broadcast lost
        # asyncio.get_event_loop in a sync context sometimes returns a
        # non-running loop. Use threadsafe scheduling when we're outside
        # the loop's thread.
        if loop.is_running():
            asyncio.ensure_future(self._fanout(run_id, payload), loop=loop)
        else:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._fanout(run_id, payload), loop)
            except RuntimeError:
                pass

    async def _fanout(self, run_id: str, payload: dict) -> None:
        async with self._lock:
            arr = list(self._subs.get(run_id, []))
        for _ws, q in arr:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.debug("Client send buffer full for run %s", run_id[:8])


client_hub = ClientHub()


async def handle_client_run_ws(ws: "WebSocket", run_id: str) -> None:
    """Browser WS handler for /api/forge/ws/runs/{run_id}.

    Subscribes, sends one immediate `run_status` snapshot, then pumps
    queued broadcasts until the client disconnects.
    """
    from fastapi import WebSocketDisconnect
    await ws.accept()

    # AUTH: browsers can't set Authorization on a WS, so the client passes its
    # JWT as ?token=. Validate it and confirm the run belongs to the caller's
    # org before subscribing — otherwise anyone could watch any run by id.
    payload = _auth_ws_token(ws.query_params.get("token", ""))
    if not payload:
        await ws.close(code=4401)
        return
    from backend.db import set_current_org
    set_current_org(payload["org_id"])
    from backend.forge import services as _svc
    if not _svc.get_run(run_id):   # org-scoped — None if foreign-org run_id
        await ws.close(code=4403)
        return

    q = await client_hub.subscribe(run_id, ws)

    # Initial snapshot so the client doesn't have to poll the REST
    # endpoint separately on connect.
    try:
        run = _svc.get_run(run_id)
        if run:
            await ws.send_json({
                "type": "run_status",
                "run_id": run_id,
                "status": run.get("status"),
                "outcome": run.get("outcome"),
                "initial": True,
            })
    except Exception as exc:
        logger.debug("initial snapshot failed run=%s: %s", run_id[:8], exc)

    async def pump() -> None:
        while True:
            msg = await q.get()
            try:
                await ws.send_json(msg)
            except Exception:
                break

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            await ws.receive_text()  # keep-alive
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        pump_task.cancel()
        await client_hub.unsubscribe(run_id, ws)


def _auth_ws_token(token: str, *, require_admin: bool = False) -> dict | None:
    """Validate a JWT — or the dev-only static API key — presented over a
    WebSocket. Returns the payload (with org_id) or None. WebSockets bypass the
    HTTP auth dependencies, so every WS handler must call this explicitly."""
    if not token:
        return None
    from backend.jwt_auth import _dev_bypass_payload, decode_token
    # Same shortcut the HTTP path takes: a local daemon started with
    # AGENTIRA_DAEMON_API_KEY connects without a browser login. Gated on
    # AGENTIRA_ENV=dev inside _dev_bypass_payload, so it is off in prod.
    payload = _dev_bypass_payload(token)
    if payload is None:
        try:
            payload = decode_token(token)
        except Exception:  # noqa: BLE001 — any decode/expiry error → unauthenticated
            return None
    if not payload.get("org_id"):
        return None
    if require_admin:
        from backend.jwt_auth import payload_roles
        if "admin" not in payload_roles(payload):
            return None
    return payload


def _runtimes_in_org(runtime_ids: list[str], org_id: str) -> list[str]:
    """Subset of runtime_ids actually owned by org_id (defends against a daemon
    claiming another org's runtime to receive its dispatch frames)."""
    if not runtime_ids:
        return []
    from backend.db import privileged, SessionLocal
    from backend.forge.models import ForgeRuntime
    with privileged():
        db = SessionLocal()
        try:
            rows = (db.query(ForgeRuntime.id)
                    .filter(ForgeRuntime.id.in_(runtime_ids),
                            ForgeRuntime.org_id == org_id).all())
            return [r[0] for r in rows]
        finally:
            db.close()


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
    claimed_runtime_ids = init.get("runtime_ids", [])
    if not daemon_id:
        await ws.close(code=4003)
        return

    # AUTH: daemon must present an admin JWT (from `agentira daemon login`),
    # via the Authorization header (preferred) or the init frame (fallback for
    # proxies that strip WS headers).
    hdr = ws.headers.get("authorization", "")
    bearer = hdr[7:] if hdr.lower().startswith("bearer ") else ""
    payload = _auth_ws_token(bearer or init.get("token", ""), require_admin=True)
    if not payload:
        logger.warning("daemon ws: rejected unauthenticated/non-admin connect")
        await ws.close(code=4401)
        return
    org_id = payload["org_id"]
    # Only register runtimes this org actually owns — never another org's.
    runtime_ids = _runtimes_in_org(claimed_runtime_ids, org_id)
    dropped = set(claimed_runtime_ids) - set(runtime_ids)
    if dropped:
        logger.warning("daemon ws: dropped %d unowned runtime_ids for org %s",
                       len(dropped), org_id)

    conn = DaemonConnection(ws, daemon_id, runtime_ids)
    await hub.connect(conn)

    # ADR 009 / B5: ack the registration as the first frame so the daemon
    # knows the hub actually holds its connection. A socket that "connected"
    # but never registered (half-open) silently dropped every dispatch — the
    # daemon now treats a missing ack as a failed connect and reconnects.
    try:
        await ws.send_json({"type": "registered", "daemon_id": daemon_id})
    except Exception:  # noqa: BLE001 — if this fails the socket is dead anyway
        await hub.disconnect(daemon_id, expected=conn)
        return

    pump_task = asyncio.create_task(conn.write_pump())
    # AP-361: a redeployed proxy can leave the TCP socket half-open — the
    # daemon side stops delivering frames but recv() here never raises, so
    # the hub keeps a dead connection registered forever and every dispatch
    # to it silently vanishes. Poll receive_text() with a bounded wait; on
    # each timeout, probe with an app-level ping, and give up (deregister)
    # once WS_HEARTBEAT_TIMEOUT_S has passed with no frame of any kind.
    last_activity = time.monotonic()
    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=WS_HEARTBEAT_INTERVAL_S)
            except asyncio.TimeoutError:
                if time.monotonic() - last_activity > WS_HEARTBEAT_TIMEOUT_S:
                    logger.warning(
                        "Daemon %s heartbeat timeout (no frames for %.0fs) — deregistering",
                        daemon_id[:8], WS_HEARTBEAT_TIMEOUT_S,
                    )
                    break
                await ws.send_json({"type": "ping"})
                continue
            last_activity = time.monotonic()
            try:
                frame = json.loads(raw)
            except Exception:
                frame = None
            if isinstance(frame, dict) and frame.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        pump_task.cancel()
        # Pass our own connection object so the hub only pops the slot if
        # WE'RE the one still registered (reconnect-safe).
        await hub.disconnect(daemon_id, expected=conn)
