"""HTTP webhook receiver for the Agentira daemon.

Listens on a configurable port for POST /webhook events pushed by the
Agentira backend.  When a valid payload arrives it is placed on an
event queue and a threading.Event is set to wake the daemon's main loop.

stdlib only — no external dependencies.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger("agentira_daemon.webhook")


class _Handler(BaseHTTPRequestHandler):
    """Minimal HTTP handler — only POST /webhook is supported."""

    # Injected by WebhookReceiver before creating the server
    event_queue: queue.Queue
    wake_event: threading.Event
    token: str

    def do_POST(self) -> None:
        if self.path != "/webhook":
            self._respond(404, {"error": "not found"})
            return

        # Token validation
        if self.server.token:
            received = self.headers.get("X-Agentira-Token", "")
            if received != self.server.token:
                logger.warning("Webhook rejected — invalid token from %s", self.client_address[0])
                self._respond(403, {"error": "forbidden"})
                return

        # Parse body
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Webhook bad JSON from %s: %s", self.client_address[0], exc)
            self._respond(400, {"error": "invalid JSON"})
            return

        event = payload.get("event", "unknown")
        task_id = payload.get("task_id", "")
        logger.info("Webhook received: event=%s task_id=%s", event, task_id)

        self.server.event_queue.put(payload)
        self.server.wake_event.set()
        self._respond(200, {"ok": True})

    def do_GET(self) -> None:
        self._respond(404, {"error": "not found"})

    def _respond(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: ARG002
        # Suppress the default per-request access log noise from http.server
        pass


class _AgentiraHTTPServer(HTTPServer):
    """HTTPServer subclass that carries shared state for the handler."""

    def __init__(
        self,
        address: tuple[str, int],
        event_queue: queue.Queue,
        wake_event: threading.Event,
        token: str,
    ) -> None:
        self.event_queue = event_queue
        self.wake_event = wake_event
        self.token = token
        super().__init__(address, _Handler)


class WebhookReceiver:
    """Background HTTP server that receives push events from Agentira.

    Usage::

        q = queue.Queue()
        wake = threading.Event()
        receiver = WebhookReceiver(port=9111, event_queue=q, wake_event=wake, token="secret")
        receiver.start()
        # … main loop …
        receiver.stop()
    """

    def __init__(
        self,
        port: int,
        event_queue: queue.Queue,
        wake_event: threading.Event,
        token: str = "",
    ) -> None:
        self.port = port
        self._server: _AgentiraHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._queue = event_queue
        self._wake = wake_event
        self._token = token

    def start(self) -> None:
        """Start the HTTP server in a background daemon thread."""
        if self.port == 0:
            logger.info("Webhook receiver disabled (port=0)")
            return
        self._server = _AgentiraHTTPServer(
            ("0.0.0.0", self.port),
            event_queue=self._queue,
            wake_event=self._wake,
            token=self._token,
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="webhook-receiver",
            daemon=True,
        )
        self._thread.start()
        auth = "token auth" if self._token else "no auth (localhost-safe)"
        logger.info("Webhook receiver listening on :%d — %s", self.port, auth)

    def stop(self) -> None:
        """Stop the HTTP server."""
        if self._server:
            self._server.shutdown()
            logger.info("Webhook receiver stopped.")
