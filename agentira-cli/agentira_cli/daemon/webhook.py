"""Inbound webhook receiver — direct port of agents/webhook_receiver.py."""

from __future__ import annotations

import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger("agentira.daemon.webhook")


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/webhook":
            self._respond(404, {"error": "not found"})
            return
        if self.server.token:
            if self.headers.get("X-Agentira-Token", "") != self.server.token:
                logger.warning("Webhook rejected — invalid token")
                self._respond(403, {"error": "forbidden"})
                return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            self._respond(400, {"error": "invalid JSON"})
            return
        logger.info("Webhook: event=%s task=%s", payload.get("event"), payload.get("task_id"))
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
        pass


class _AgentiraHTTPServer(HTTPServer):
    def __init__(self, address, event_queue, wake_event, token):
        self.event_queue = event_queue
        self.wake_event = wake_event
        self.token = token
        super().__init__(address, _Handler)


class WebhookReceiver:
    def __init__(self, port: int, event_queue: queue.Queue,
                 wake_event: threading.Event, token: str = "") -> None:
        self.port = port
        self._server = None
        self._queue = event_queue
        self._wake = wake_event
        self._token = token

    def start(self) -> None:
        if self.port == 0:
            return
        self._server = _AgentiraHTTPServer(
            ("0.0.0.0", self.port), self._queue, self._wake, self._token
        )
        threading.Thread(target=self._server.serve_forever,
                         name="webhook-receiver", daemon=True).start()
        logger.info("Webhook receiver on :%d", self.port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
