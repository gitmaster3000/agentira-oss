"""Synchronous REST client for Agentira."""

from __future__ import annotations

import json
import urllib.request
import urllib.parse


class AgentiraClient:
    """Synchronous REST client for Agentira."""

    def __init__(self, base_url: str, api_key: str, bot_name: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key  = api_key
        self.bot_name = bot_name
        self._headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        if bot_name:
            self._headers["actor"] = bot_name
        else:
            self._headers["actor"] = "system"

    def _get(self, path: str, params: dict | None = None) -> object:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(url, headers=self._headers, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def _post(self, path: str, body: dict | None = None) -> object:
        data = json.dumps(body or {}).encode()
        req  = urllib.request.Request(
            self.base_url + path, data=data, headers=self._headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def _patch(self, path: str, body: dict | None = None) -> object:
        data = json.dumps(body or {}).encode()
        req  = urllib.request.Request(
            self.base_url + path, data=data, headers=self._headers, method="PATCH"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def resolve_bot_name(self) -> str:
        """Call GET /api/profiles/me to resolve bot name from API key."""
        data = self._get("/api/profiles/me", {"actor": self.bot_name or "system"})
        self.bot_name = data.get("name", "system")
        self._headers["actor"] = self.bot_name
        return self.bot_name

    def list_my_tasks(self, status: str | None = None) -> list[dict]:
        """List tasks assigned to this bot, optionally filtered by status."""
        return self._get("/api/tasks", {"assignee": self.bot_name, "status": status})

    def get_task(self, task_id: str) -> dict:
        return self._get(f"/api/tasks/{task_id}")

    def move_task(self, task_id: str, status: str) -> dict:
        return self._post(f"/api/tasks/{task_id}/move", {"status": status, "actor": self.bot_name})

    def add_comment(self, task_id: str, comment: str) -> dict:
        return self._post(f"/api/tasks/{task_id}/comment", {"comment": comment, "actor": self.bot_name})

    def get_notifications(self, unread_only: bool = True) -> list[dict]:
        return self._get("/api/notifications", {"unread_only": str(unread_only).lower(), "actor": self.bot_name})

    def mark_notification_read(self, notification_id: str) -> bool:
        path = f"/api/notifications/{notification_id}/read?actor={urllib.parse.quote(self.bot_name)}"
        self._patch(path)
        return True

    def get_my_profile(self) -> dict:
        """Return the full profile for the authenticated bot."""
        return self._get("/api/profiles/me", {"actor": self.bot_name})

    def update_my_profile(self, **kwargs) -> dict:
        """Update the current bot's profile fields (webhook_url, display_name, etc.)."""
        profile = self.get_my_profile()
        return self._patch(f"/api/profiles/{profile['id']}", kwargs)

    def close(self) -> None:
        pass
