"""Agentira agent model must reach OpenClaw: sessions.patch before chat.send.

chat.send's schema is closed (no model param), so the per-turn override is a
sessions.patch {key, model} on the turn's session. Empty model = untouched.
"""

from __future__ import annotations

import json

from tests.test_openclaw_ws_logging import _handshake, _run

MODEL = "openrouter/moonshotai/kimi-k2.7-code"


def _tail(text="ok"):
    return [
        {"type": "res", "id": "s1", "ok": True, "payload": {}},
        {"type": "event", "event": "chat", "payload": {"text": text}},
        {"type": "event", "event": "chat.complete", "payload": {}},
    ]


def _frames(fake):
    return [json.loads(s) for s in fake.sent]


def test_model_patches_session_before_chat_send(tmp_path):
    script = [*_handshake(), {"type": "res", "id": "p1", "ok": True}, *_tail()]
    res, fake = _run(tmp_path, script, model=MODEL)

    assert res.success is True
    methods = [f.get("method") for f in _frames(fake)]
    assert methods.index("sessions.patch") < methods.index("chat.send")
    patch = next(f for f in _frames(fake) if f.get("method") == "sessions.patch")
    assert patch["params"] == {"key": "agent:ar-abcd1234:task:t1", "model": MODEL}


def test_empty_model_sends_no_patch(tmp_path):
    res, fake = _run(tmp_path, [*_handshake(), *_tail()], model="")

    assert res.success is True
    assert "sessions.patch" not in [f.get("method") for f in _frames(fake)]


def test_rejected_model_fails_the_run_without_chat_send(tmp_path):
    script = [*_handshake(), {"type": "res", "id": "p1", "ok": False,
                              "error": {"message": "Model x is not available"}}]
    res, fake = _run(tmp_path, script, model=MODEL)

    assert res.success is False
    assert MODEL in res.error
    assert "chat.send" not in [f.get("method") for f in _frames(fake)]
