"""REST client for AgentIRA backend — runtime host endpoints only."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request


class AgentiraClient:
    def __init__(self, base_url: str, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    def _get(self, path: str, params: dict | None = None) -> object:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(url, headers=self._headers, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def _post(self, path: str, body: dict | None = None) -> object:
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(self.base_url + path, data=data, headers=self._headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    # ── Runtime registration ─────────────────────────────────────────────

    def register_runtimes(self, daemon_id: str, device_name: str | None,
                          runtimes: list[dict]) -> dict:
        return self._post("/api/forge/runtimes/register", {
            "daemon_id": daemon_id,
            "device_name": device_name,
            "runtimes": runtimes,
        })

    def heartbeat_runtimes(self, daemon_id: str, providers: list[str]) -> dict:
        return self._post("/api/forge/runtimes/heartbeat", {
            "daemon_id": daemon_id,
            "providers": providers,
        })

    def list_runtimes(self) -> list[dict]:
        return self._get("/api/forge/runtimes")

    def post_run_events(self, run_id: str, daemon_id: str, events: list) -> dict:
        return self._post(f"/api/forge/runs/{run_id}/events", {
            "daemon_id": daemon_id,
            "events": events,
        })

    def complete_run(self, run_id: str, daemon_id: str, *, success: bool,
                     input_tokens: int = 0, output_tokens: int = 0, error: str = "") -> dict:
        return self._post(f"/api/forge/runs/{run_id}/complete-daemon", {
            "daemon_id": daemon_id,
            "success": success,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "error": error,
        })

    def post_agent_chat_events(self, agent_id: str, daemon_id: str, chat_id: str, events: list) -> dict:
        return self._post(f"/api/forge/agents/{agent_id}/chat-events", {
            "daemon_id": daemon_id,
            "chat_id": chat_id,
            "events": events,
        })

    def get_agent(self, agent_id: str) -> dict:
        return self._get(f"/api/forge/agents/{agent_id}")
