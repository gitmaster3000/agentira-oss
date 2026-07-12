"""OpenClaw session_key (legacy HTTP path).

Tests the header sent by the HTTP gateway helper (still used by ollama
and for direct calls). OpenClaw daemon execution now goes through native
WS (run_openclaw_ws) which passes sessionKey in the chat.send frame.
"""

from __future__ import annotations

import asyncio
import io
import json
from unittest.mock import patch

from agentira_cli.daemon.executor import run_gateway


class _FakeResp:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False


def _capture():
    """Return (urlopen-patch, captured-requests-list)."""
    captured: list = []
    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        captured.append(req)
        return _FakeResp({
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            "model": "openclaw/agentira-runner",
        })
    return patch("agentira_cli.daemon.executor.urllib.request.urlopen",
                 side_effect=fake_urlopen), captured


def test_openclaw_dispatch_sends_session_key_header():
    p, captured = _capture()
    with p:
        res = asyncio.run(run_gateway(
            "http://127.0.0.1:18789", "tok", "runner", "hello",
            provider="openclaw",
            session_key="agentira:abcdef12:task:t1",
        ))
    assert captured, "no request made"
    headers = {k.lower(): v for k, v in captured[0].header_items()}
    assert headers.get("x-openclaw-session-key") == "agentira:abcdef12:task:t1"
    # Backend round-trips this onto forge_conversations.runtime_session_id.
    assert res.session_id == "agentira:abcdef12:task:t1"


def test_openclaw_dispatch_without_session_key_omits_header():
    p, captured = _capture()
    with p:
        asyncio.run(run_gateway(
            "http://127.0.0.1:18789", "tok", "runner", "hello",
            provider="openclaw",
        ))
    headers = {k.lower(): v for k, v in captured[0].header_items()}
    assert "x-openclaw-session-key" not in headers


def test_non_openclaw_provider_does_not_get_the_header():
    """ollama et al. share the OpenAI-compat code path but don't speak the
    x-openclaw-* extension. Make sure we don't leak the header to them."""
    p, captured = _capture()
    with p:
        asyncio.run(run_gateway(
            "http://127.0.0.1:11434", "", "model", "hello",
            provider="ollama", model="ollama/llama3",
            session_key="should-be-ignored-for-non-openclaw",
        ))
    headers = {k.lower(): v for k, v in captured[0].header_items()}
    assert "x-openclaw-session-key" not in headers
