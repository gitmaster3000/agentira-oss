"""Daemon-side WebSocket client — connects to /api/forge/daemon/ws.

Receives task_available frames from the server and wakes the poll loop immediately
instead of waiting for the next poll interval.

Designed to run as a background thread alongside the main daemon loop.
Falls back gracefully when the server doesn't support WS — daemon still polls.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time

logger = logging.getLogger("agentira.daemon.ws")

_RECONNECT_DELAYS = [1, 2, 5, 10, 30, 60]  # seconds, last value repeated


class DaemonWsClient:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        daemon_id: str,
        runtime_ids: list[str],
        wake_event: threading.Event,
        task_queue: queue.Queue | None = None,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._daemon_id = daemon_id
        self._runtime_ids = runtime_ids
        self._wake = wake_event
        self._task_queue = task_queue
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="daemon-ws", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _ws_url(self) -> str:
        base = self._api_url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base}/api/forge/daemon/ws"

    def _run(self) -> None:
        delay_idx = 0
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
                delay_idx = 0  # successful connection — reset backoff
            except Exception as exc:
                delay = _RECONNECT_DELAYS[min(delay_idx, len(_RECONNECT_DELAYS) - 1)]
                logger.debug("WS disconnected (%s) — reconnect in %ds", exc, delay)
                delay_idx += 1
                self._stop.wait(timeout=delay)

    def _connect_and_listen(self) -> None:
        try:
            import websockets.sync.client as _ws
        except ImportError:
            logger.debug("websockets not installed — WS push disabled, using poll only")
            self._stop.wait()  # block forever; poll loop handles everything
            return

        url = self._ws_url()
        headers = {"Authorization": f"Bearer {self._api_key}"}
        # certifi-backed TLS for wss:// (macOS python builds lack root CAs).
        ws_ssl = None
        if url.startswith("wss://"):
            from agentira_cli.transport.tls import ssl_context
            ws_ssl = ssl_context()

        # Open with library-side ping/pong so the underlying socket is
        # actively probed every 20s. Without this, a half-closed TCP
        # connection looks alive to recv() forever and the daemon
        # silently stops receiving triggers (observed: 13h dead zone).
        with _ws.connect(
            url,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=10,
            ssl=ws_ssl,
        ) as ws:
            # Send identity frame
            ws.send(json.dumps({
                "daemon_id": self._daemon_id,
                "runtime_ids": self._runtime_ids,
                # Fallback auth for proxies that strip the Authorization header.
                "token": self._api_key,
            }))

            # ADR 009 / B5: the backend acks registration as the very first
            # frame (sent right after it adds us to the hub, before any
            # dispatch). If we don't get it, the connection is half-open —
            # the hub doesn't hold us and every dispatch would silently drop.
            # Treat a missing/wrong ack as a failed connect so the outer loop
            # reconnects with backoff instead of sitting in a dead zone.
            try:
                ack = json.loads(ws.recv(timeout=10))
            except (TimeoutError, Exception) as exc:
                raise ConnectionError(
                    f"no WS registration ack within 10s ({exc}) — reconnecting")
            if ack.get("type") != "registered":
                raise ConnectionError(
                    f"unexpected first WS frame (want 'registered'): {ack!r}")
            logger.info("WS connected + registered to %s", url)

            while not self._stop.is_set():
                try:
                    raw = ws.recv(timeout=30)
                except TimeoutError:
                    # Lib-managed ping handles socket-level keepalive, but a
                    # half-open proxy hop can absorb those silently without
                    # ever surfacing an error here. Send an app-level ping
                    # too so the server can detect and deregister us if it's
                    # not getting through — see handle_daemon_ws heartbeat.
                    ws.send(json.dumps({"type": "ping"}))
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                if msg.get("type") == "ping":
                    ws.send(json.dumps({"type": "pong"}))
                elif msg.get("type") == "pong":
                    continue
                elif msg.get("type") == "trigger":
                    logger.info(
                        "WS trigger received: trace=%s kind=%s agent=%s run=%s",
                        msg.get("trace_id", ""),
                        msg.get("kind", ""),
                        msg.get("agent_id", ""),
                        msg.get("run_id", "") or "-",
                    )
                    if self._task_queue is not None:
                        self._task_queue.put(msg)
                    self._wake.set()
                elif msg.get("type") in ("cancel", "pause", "resume", "integrate"):
                    logger.info(
                        "WS %s received: trace=%s run=%s",
                        msg.get("type"),
                        msg.get("trace_id", ""),
                        msg.get("run_id", "") or "-",
                    )
                    if self._task_queue is not None:
                        self._task_queue.put(msg)
                    self._wake.set()
