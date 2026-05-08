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

        with _ws.connect(url, additional_headers=headers) as ws:
            # Send identity frame
            ws.send(json.dumps({
                "daemon_id": self._daemon_id,
                "runtime_ids": self._runtime_ids,
            }))
            logger.info("WS connected to %s", url)

            while not self._stop.is_set():
                try:
                    raw = ws.recv(timeout=30)
                except TimeoutError:
                    ws.send("ping")  # keep-alive
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                if msg.get("type") == "trigger":
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
                elif msg.get("type") in ("cancel", "pause", "resume"):
                    logger.info(
                        "WS %s received: trace=%s run=%s",
                        msg.get("type"),
                        msg.get("trace_id", ""),
                        msg.get("run_id", "") or "-",
                    )
                    if self._task_queue is not None:
                        self._task_queue.put(msg)
                    self._wake.set()
