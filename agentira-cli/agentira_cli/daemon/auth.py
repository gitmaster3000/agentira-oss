"""Keeps the daemon signed in.

`agentira daemon login` stores a short-lived access JWT plus a long-lived
refresh token in credentials.json. TokenManager renews the access token before
it expires and again whenever the server answers 401, and says so loudly (one
ERROR line per 10 minutes) when it cannot — instead of failing silently.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from agentira_cli.transport.tls import ssl_context

logger = logging.getLogger("agentira.daemon.auth")

REFRESH_WHEN_LEFT_S = 24 * 3600   # renew when under a day remains
ERROR_LOG_EVERY_S = 600           # at most one signed-out ERROR per 10 min
_BACKOFF_S = [30, 60, 120, 300, 600]  # between failed refresh attempts

SIGNED_OUT_MSG = "Agentira daemon is signed out — run `agentira daemon login`"


def _post_json(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as r:
        return json.loads(r.read().decode())


def token_seconds_left(token: str, now: float) -> Optional[float]:
    """Seconds until a JWT's `exp`, read without verifying (the server does
    that). None if the token isn't a readable JWT (e.g. a static API key)."""
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return float(claims["exp"]) - now
    except (IndexError, ValueError, KeyError, TypeError):
        return None


class TokenManager:
    def __init__(self, *, api_url: str, token: str, refresh_token: str = "",
                 credentials_file=None,
                 post: Callable[[str, dict], dict] = _post_json,
                 clock: Callable[[], float] = time.time) -> None:
        self._api_url = api_url.rstrip("/")
        self._token = token
        self._refresh_token = refresh_token or ""
        self._file = credentials_file
        self._post = post
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._retry_at = 0.0
        self._last_logged = float("-inf")
        self._last_kind = "signed out"
        # Last access token known to be in the credentials file (ours or
        # theirs) — anything else there came from a fresh `daemon login`.
        self._file_token = token

    @classmethod
    def from_credentials(cls, *, credentials_file, api_url: str, api_key: str):
        """Manager for a daemon running on the `daemon login` token, else None
        (static/dev keys and `--api-key` overrides are left alone)."""
        try:
            creds = json.loads(credentials_file.read_text())
        except (OSError, ValueError):
            return None
        if not creds.get("token") or creds["token"] != api_key:
            return None
        return cls(api_url=api_url, token=api_key,
                   refresh_token=creds.get("refresh_token", ""),
                   credentials_file=credentials_file)

    @property
    def access_token(self) -> str:
        return self._token

    # ── public ────────────────────────────────────────────────────────────

    def ensure_fresh(self) -> None:
        """Proactive renewal: call before talking to the server."""
        with self._lock:
            left = token_seconds_left(self._token, self._clock())
            if left is None or left >= REFRESH_WHEN_LEFT_S:
                return
            self._renew()

    def refresh(self, rejected_token: str) -> bool:
        """Reactive renewal after the server rejected `rejected_token`.
        True if a different, usable token is now available to retry with."""
        with self._lock:
            if self._token != rejected_token:  # another thread already did it
                return True
            return self._renew()

    # ── internals ─────────────────────────────────────────────────────────

    def _renew(self) -> bool:
        if self._adopt_from_file():
            return True
        if self._clock() < self._retry_at:
            self._report(self._last_kind)
            return False
        if not self._refresh_token:
            self._failed(rejected=True)
            return False
        try:
            res = self._post(f"{self._api_url}/api/auth/cli/refresh",
                             {"refresh_token": self._refresh_token})
            token, refresh = res["token"], res["refresh_token"]
        except urllib.error.HTTPError as exc:
            self._failed(rejected=exc.code in (400, 401, 403))
            return False
        except Exception as exc:  # noqa: BLE001 — network, bad JSON, …
            logger.debug("token refresh failed: %s", exc)
            self._failed(rejected=False)
            return False
        self._token, self._refresh_token = token, refresh
        self._failures, self._retry_at = 0, 0.0
        self._save()
        logger.info("Agentira daemon access token renewed")
        return True

    def _adopt_from_file(self) -> bool:
        """`agentira daemon login` run while we're up: pick up its tokens, so
        signing in again fixes a running daemon without a restart."""
        if self._file is None:
            return False
        try:
            creds = json.loads(self._file.read_text())
        except (OSError, ValueError):
            return False
        token = creds.get("token", "")
        if not token or token == self._file_token:
            return False
        self._file_token = token
        self._token = token
        self._refresh_token = creds.get("refresh_token", "")
        self._failures, self._retry_at = 0, 0.0
        logger.info("Agentira daemon picked up new sign-in from credentials file")
        return True

    def _save(self) -> None:
        if self._file is None:
            return
        try:
            try:
                creds = json.loads(self._file.read_text())
            except (OSError, ValueError):
                creds = {"api_url": self._api_url}
            creds.update(token=self._token, refresh_token=self._refresh_token)
            tmp = self._file.with_name(self._file.name + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(creds))
            os.replace(tmp, self._file)
            self._file_token = self._token
        except OSError as exc:
            logger.warning("could not save renewed credentials: %s", exc)

    def _failed(self, *, rejected: bool) -> None:
        self._retry_at = self._clock() + _BACKOFF_S[min(self._failures, len(_BACKOFF_S) - 1)]
        self._failures += 1
        self._last_kind = "signed out" if rejected or not self._refresh_token else "unreachable"
        self._report(self._last_kind)

    def _report(self, kind: str) -> None:
        now = self._clock()
        if now - self._last_logged < ERROR_LOG_EVERY_S:
            return
        self._last_logged = now
        if kind == "unreachable":
            logger.error("Agentira daemon could not reach %s to renew its sign-in "
                         "— will keep retrying", self._api_url)
        else:
            logger.error(SIGNED_OUT_MSG)
