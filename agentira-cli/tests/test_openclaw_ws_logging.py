"""run_openclaw_ws must tee its stream to the per-run stdout.log / stderr.log.

Regression: the native WS path streamed events only to the backend (on_event)
and never wrote the run dir, so openclaw/ollama runs left stdout.log stale and
stderr.log empty — the run was invisible for debugging while claude runs were
fully captured. See the "talks twice and dies, logs show nothing" investigation.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from unittest.mock import patch

from agentira_cli.daemon.executor import run_openclaw_ws


class _FakeWS:
    """Minimal scripted websocket: send() is a sink, recv() pops the script."""

    def __init__(self, script: list[dict]):
        self._script = [json.dumps(x) for x in script]
        self.sent: list[str] = []

    def send(self, raw: str) -> None:
        self.sent.append(raw)

    def recv(self) -> str:
        if not self._script:
            raise ConnectionError("closed")
        return self._script.pop(0)

    def close(self) -> None:
        pass


def _run(tmp_path, script, **kwargs):
    fake = _FakeWS(script)
    # `websocket` (websocket-client) isn't a test dep; inject a stub module so
    # the `import websocket` inside _ws_main resolves to our fake.
    stub = types.ModuleType("websocket")
    stub.create_connection = lambda *a, **k: fake
    with patch.dict(sys.modules, {"websocket": stub}):
        res = asyncio.run(run_openclaw_ws(
            "http://127.0.0.1:18789", "tok", "agentira-runner", "hi",
            session_key="agentira:abcd1234:task:t1",
            **kwargs,
        ))
    return res, fake


def _ok_script(text="hello from heretic"):
    return [
        {},                                                  # challenge
        {"ok": True},                                        # connect hello
        {"ok": True},                                        # sub ack
        {"type": "res", "id": "s1", "ok": True,
         "payload": {"usage": {"prompt_tokens": 5, "completion_tokens": 2}}},
        {"type": "event", "event": "chat",
         "payload": {"text": text, "model": "ollama/qwen3.6"}},
        {"type": "event", "event": "chat.complete", "payload": {}},
    ]


def test_stream_events_are_teed_to_stdout_log(tmp_path):
    log = tmp_path / "run" / "stdout.log"
    res, _ = _run(tmp_path, _ok_script(), stdout_log_path=str(log))

    assert res.success is True
    assert res.text == "hello from heretic"
    assert log.exists(), "stdout.log was not written"
    lines = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    texts = [l for l in lines if l.get("type") == "text"]
    assert texts and texts[0]["text"] == "hello from heretic"


def test_fatal_is_teed_to_stderr_log(tmp_path):
    stderr = tmp_path / "run" / "stderr.log"
    # connect hello returns ok=False -> _fatal path
    script = [{}, {"ok": False, "error": "handshake rejected"}]
    res, _ = _run(tmp_path, script, stderr_log_path=str(stderr))

    assert res.success is False
    assert stderr.exists(), "stderr.log was not written"
    body = stderr.read_text()
    assert "handshake rejected" in body
    assert "trace=" in body


def test_error_line_carries_trace_id(tmp_path):
    stderr = tmp_path / "run" / "stderr.log"
    # no content produced -> result.error set, teed with trace
    script = [{}, {"ok": True}, {"ok": True},
              {"type": "event", "event": "chat.complete", "payload": {}}]
    res, _ = _run(tmp_path, script, stderr_log_path=str(stderr),
                  trace_id="deadbeef")
    assert res.success is False
    assert "deadbeef" in stderr.read_text()
