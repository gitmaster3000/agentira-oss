"""OpenClaw native WebSocket turn execution.

All OpenClaw chat.send / event-stream protocol lives here — not in the
shared daemon executor. The daemon calls Runtime.execute_turn; only
OpenClawRuntime imports this module.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from typing import Optional

from agentira_cli.daemon.executor import StreamResult
from agentira_cli.runtimes.gateway_connect import build_connect_params

logger = logging.getLogger("agentira.runtime.openclaw_ws")

# ── OpenClaw gateway protocol (wire names) ──────────────────────────────────
# Single place to update if OpenClaw renames events / fields / RPCs.
# Verified against openclaw dist (2026.4.x): GATEWAY_EVENTS + agent stream=tool.

# WS frame.event values
OC_EVENT_AGENT = "agent"
OC_EVENT_CHAT = "chat"
OC_EVENT_SESSION_TOOL = "session.tool"
OC_EVENT_SESSION_MESSAGE = "session.message"
OC_EVENT_CONNECT_CHALLENGE = "connect.challenge"

# Chat-family events that carry assistant text / terminal state
OC_CHAT_EVENTS: frozenset[str] = frozenset({
    OC_EVENT_CHAT,
    "chat.message",
    OC_EVENT_SESSION_MESSAGE,
    "message",
    "chat.inject",
})

# Events that may signal terminal model/runtime failure
OC_ERROR_EVENTS: frozenset[str] = frozenset({
    OC_EVENT_CHAT,
    "chat.message",
    OC_EVENT_SESSION_MESSAGE,
    "message",
    OC_EVENT_AGENT,
    "agent.error",
    "run.error",
})

# Turn-complete event names (stop draining)
OC_COMPLETE_EVENTS: frozenset[str] = frozenset({
    "chat.complete",
    "session.complete",
    "run.finished",
    "chat.done",
})

# Tool lifecycle: primary wire names (real OpenClaw 2026.4+)
#   event: agent|session.tool, payload.stream == "tool", data.phase = start|update|result
OC_TOOL_EVENT_NAMES: frozenset[str] = frozenset({
    OC_EVENT_SESSION_TOOL,
    "session.tools",  # defensive alias
    "tool",
    "tool_use",
    "agent.tool",
})
# Older / invented result-only names we still accept
OC_TOOL_RESULT_EVENT_NAMES: frozenset[str] = frozenset({
    "session.tool.result",
    "tool_result",
    "tool.result",
    "agent.tool_result",
})

OC_STREAM_TOOL = "tool"

# data.phase values on stream=tool frames
OC_TOOL_PHASE_START: frozenset[str] = frozenset({"start", "begin", ""})
OC_TOOL_PHASE_UPDATE: frozenset[str] = frozenset({"update", "delta", "progress"})
OC_TOOL_PHASE_RESULT: frozenset[str] = frozenset({"result", "end", "error", "failed"})
OC_TOOL_PHASE_ERROR: frozenset[str] = frozenset({"error", "failed"})

# Payload field keys (nested under payload / payload.data)
OC_KEY_DATA = "data"
OC_KEY_STREAM = "stream"
OC_KEY_PHASE = "phase"
OC_KEY_NAME = "name"
OC_KEY_TOOL = "tool"
OC_KEY_TOOL_NAME = "toolName"
OC_KEY_TOOL_CALL_ID = "toolCallId"
OC_KEY_TOOL_CALL_ID_SNAKE = "tool_call_id"
OC_KEY_ARGS = "args"
OC_KEY_INPUT = "input"
OC_KEY_PARAMETERS = "parameters"
OC_KEY_RESULT = "result"
OC_KEY_OUTPUT = "output"
OC_KEY_PARTIAL_RESULT = "partialResult"
OC_KEY_CONTENT = "content"
OC_KEY_IS_ERROR = "isError"
OC_KEY_STATE = "state"
OC_KEY_MESSAGE = "message"
OC_KEY_MODEL = "model"
OC_KEY_TEXT = "text"

# Chat state / role values
OC_STATE_FINAL: frozenset[str] = frozenset({"final", "done", "complete", "completed"})
OC_STATE_ERROR: frozenset[str] = frozenset({"error", "aborted"})
OC_ROLE_USER_SYSTEM: frozenset[str] = frozenset({"user", "system"})
OC_ROLE_ASSISTANT = "assistant"

# Gateway RPC methods
OC_RPC_SESSIONS_SUBSCRIBE = "sessions.subscribe"
OC_RPC_SESSIONS_MESSAGES_SUBSCRIBE = "sessions.messages.subscribe"
OC_RPC_CHAT_SEND = "chat.send"
OC_RPC_CONNECT = "connect"

# Internal daemon→backend event types (Agentira contract, not OpenClaw wire)
EVT_TEXT = "text"
EVT_TOOL_USE = "tool_use"
EVT_TOOL_RESULT = "tool_result"
EVT_TOOL_CALL_ID = "tool_call_id"  # optional field on internal tool events


def _tee_json_line(log_f, obj: dict) -> None:
    if log_f is None:
        return
    try:
        log_f.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
    except OSError:
        pass


def _tee_stderr(log_f, msg: str, *, trace_id: str = "") -> None:
    if log_f is None:
        return
    try:
        log_f.write((f"{msg} trace={trace_id}\n").encode())
    except OSError:
        pass


def _format_openclaw_error(raw) -> str:
    """Turn OpenClaw RPC / chat error payloads into a plain-language failure.

    OpenClaw model failures arrive as chat events:
      {state: "error", errorMessage: "All models failed … ECONNREFUSED …"}
    RPC failures are {code, message} dicts. Without this, the daemon only
    reports "no content produced" and the real cause stays in gateway logs.
    """
    if raw is None:
        return ""
    if isinstance(raw, dict):
        msg = (
            raw.get("errorMessage")
            or raw.get("message")
            or raw.get("error")
            or raw.get("summary")
            or ""
        )
        if isinstance(msg, dict):
            msg = msg.get("message") or str(msg)
        code = raw.get("code") or ""
        text = str(msg or raw).strip()
    else:
        code = ""
        text = str(raw).strip()
    if not text:
        return ""
    low = text.lower()
    if "econnrefused" in low and ("11434" in text or "ollama" in low):
        return (
            "OpenClaw could not reach Ollama (nothing listening on port 11434). "
            "Start Ollama and try again. "
            f"Details: {text}"
        )
    if "all models failed" in low or "connection refused by the provider" in low:
        return (
            "OpenClaw's language model backend failed — the model provider "
            f"is down or unreachable. Details: {text}"
        )
    if "session file locked" in low or "session_write_lock" in low:
        return (
            "OpenClaw session is busy/locked (usually a previous chat was "
            "cancelled mid-turn). Wait a few seconds and try once, or run: "
            "rm -f ~/.openclaw/agents/main/sessions/*.lock && openclaw gateway restart. "
            f"Details: {text}"
        )
    if "failed before producing" in low or "failed before reply" in low:
        return (
            "OpenClaw's agent failed before it could reply (session lock, "
            "model error, or MCP crash). Check Ollama is up and try again. "
            f"Details: {text}"
        )
    if code and code not in text:
        return f"{code}: {text}"
    return text


def _extract_chat_error(payload: dict) -> str:
    """If a chat event payload is a terminal failure, return its message."""
    if not isinstance(payload, dict):
        return ""
    state = str(payload.get(OC_KEY_STATE) or "").lower()
    err = (
        payload.get("errorMessage")
        or payload.get("error")
        or (payload.get(OC_KEY_MESSAGE) if state == "error" else None)
        or ""
    )
    if isinstance(err, dict):
        err = err.get("message") or str(err)
    err_s = str(err).strip() if err else ""
    if state in ("error", "failed", "aborted") or (
        err_s and state in OC_STATE_FINAL and payload.get(OC_KEY_IS_ERROR)
    ):
        return _format_openclaw_error(payload if err_s else {"message": state or "error"})
    if payload.get(OC_KEY_IS_ERROR) and err_s:
        return _format_openclaw_error(payload)
    return ""


def _is_failed_assistant_stub(text: str) -> bool:
    """OpenClaw sometimes writes failure stubs as 'assistant' content."""
    low = (text or "").lower().strip()
    if not low:
        return False
    return (
        "failed before producing" in low
        or "failed before reply" in low
        or low in ("[assistant turn failed]", "assistant turn failed")
        or low.startswith("[assistant turn failed")
        or "turn failed before producing content" in low
    )


def _snapshot_to_delta(prev: str, incoming: str) -> tuple[str, str, bool]:
    """Convert a cumulative text snapshot into (new_prev, text_to_emit, replace).

    OpenClaw often rebroadcasts the *full* assistant message so far on every
    chat event (not a true token delta). If we forward each snapshot as an
    appendable text event, the backend concatenates full copies and the UI
    shows the monologue looping ("Got it…" repeated N times).

    Returns:
      new_prev  — cumulative text after this event
      text      — payload for a type=text event (delta or full rewrite)
      replace   — if True, backend must SET the open bubble to `text`
                  (not append). Used when the runtime restarts / rewrites
                  the assistant message without a shared prefix.
    """
    if not incoming:
        return prev, "", False
    if not prev:
        return incoming, incoming, False
    if incoming.startswith(prev):
        return incoming, incoming[len(prev):], False
    if prev.startswith(incoming):
        # Shorter rewrite of what we already sent — skip (avoid duplicates).
        return prev, "", False
    # Non-prefix rewrite (model restarted reasoning mid-stream, etc.).
    return incoming, incoming, True


def _is_silent_reply_token(text: str) -> bool:
    """OpenClaw channel silence tokens — not real answers for Agentira chat.

    OpenClaw's agent is trained/prompted (WebChat/channel path) to reply
    exactly NO_REPLY when no response is needed. Short tokens like "NO"
    are also treated as silence prefixes. For Forge chat we always need
    a real answer — never show these as the agent reply.
    """
    t = (text or "").strip()
    if not t:
        return False
    up = t.upper()
    if up in ("NO_REPLY", "HEARTBEAT_OK", "NO"):
        return True
    if up.startswith("NO_REPLY") and len(up) <= 24:
        return True
    return False


def _first_key(d: dict, *keys: str):
    """Return the first present non-None value for keys in d."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _tool_wire_events(ename: str, payload: dict) -> list[dict]:
    """Translate OpenClaw tool lifecycle WS frames into internal events.

    Real OpenClaw (2026.4+) does **not** emit freestanding tool_use /
    session.tool.result event names. Tools arrive as:

      event: OC_EVENT_AGENT | OC_EVENT_SESSION_TOOL
      payload: {
        stream: OC_STREAM_TOOL,
        data: { phase: start|update|result, name, toolCallId, args?, result? }
      }

    Delivery:
      - agent + stream=tool → caps tool-events (toolEventRecipient on chat.send)
      - session.tool → sessions.subscribe

    We used to match invented event names and read name/args at the top level
    of the payload, so every real tool frame was silently dropped.
    """
    if not isinstance(payload, dict):
        return []

    data = payload.get(OC_KEY_DATA) if isinstance(payload.get(OC_KEY_DATA), dict) else {}
    stream = str(
        payload.get(OC_KEY_STREAM) or data.get(OC_KEY_STREAM) or ""
    ).lower()
    is_tool_frame = (
        ename in OC_TOOL_EVENT_NAMES
        or (ename == OC_EVENT_AGENT and stream == OC_STREAM_TOOL)
        or stream == OC_STREAM_TOOL
    )
    is_result_frame = ename in OC_TOOL_RESULT_EVENT_NAMES
    if not is_tool_frame and not is_result_frame:
        return []

    phase = str(
        data.get(OC_KEY_PHASE) or payload.get(OC_KEY_PHASE) or ""
    ).lower()
    tname = _first_key(
        data, OC_KEY_NAME, OC_KEY_TOOL, OC_KEY_TOOL_NAME,
    )
    if tname is None:
        tname = _first_key(payload, OC_KEY_NAME, OC_KEY_TOOL, OC_KEY_TOOL_NAME)
    tname = str(tname or "").strip()
    if not tname and not is_result_frame:
        return []

    tool_call_id = _first_key(
        data, OC_KEY_TOOL_CALL_ID, OC_KEY_TOOL_CALL_ID_SNAKE,
    )
    if tool_call_id is None:
        tool_call_id = _first_key(
            payload, OC_KEY_TOOL_CALL_ID, OC_KEY_TOOL_CALL_ID_SNAKE,
        )
    tool_call_id = str(tool_call_id or "")

    def _as_input(raw) -> object:
        return raw if raw is not None else ""

    def _as_output(raw) -> str:
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        try:
            return json.dumps(raw, ensure_ascii=False)[:8000]
        except Exception:
            return str(raw)[:8000]

    out: list[dict] = []
    # phase start → tool_use; phase result → tool_result.
    # update is partial progress — ignore for chat rows (noisy).
    if is_result_frame or phase in OC_TOOL_PHASE_RESULT:
        tout = data.get(OC_KEY_RESULT) if OC_KEY_RESULT in data else None
        if tout is None:
            tout = _first_key(data, OC_KEY_OUTPUT, OC_KEY_PARTIAL_RESULT)
        if tout is None:
            tout = _first_key(payload, OC_KEY_OUTPUT, OC_KEY_RESULT, OC_KEY_CONTENT)
        if tout is None and is_result_frame:
            tout = str(payload)[:2000]
        ev: dict = {
            "type": EVT_TOOL_RESULT,
            "tool": tname,
            "output": _as_output(tout),
        }
        if tool_call_id:
            ev[EVT_TOOL_CALL_ID] = tool_call_id
        if data.get(OC_KEY_IS_ERROR) or phase in OC_TOOL_PHASE_ERROR:
            ev["is_error"] = True
        out.append(ev)
    elif phase in OC_TOOL_PHASE_UPDATE:
        return []
    elif phase in OC_TOOL_PHASE_START or is_tool_frame:
        tin = (
            data.get(OC_KEY_ARGS)
            if OC_KEY_ARGS in data
            else _first_key(data, OC_KEY_INPUT, OC_KEY_PARAMETERS)
        )
        if tin is None:
            tin = _first_key(payload, OC_KEY_INPUT, OC_KEY_ARGS, OC_KEY_PARAMETERS) or ""
        ev = {
            "type": EVT_TOOL_USE,
            "tool": tname,
            "input": _as_input(tin),
        }
        if tool_call_id:
            ev[EVT_TOOL_CALL_ID] = tool_call_id
        out.append(ev)
    return out


def _assistant_text_from_chat_payload(payload: dict) -> str:
    """Extract assistant-visible text from an OpenClaw chat event.

    Skips user-role echoes (OpenClaw rebroadcasts the inbound message;
    treating that as assistant text made the UI show the user's own
    words as the agent reply — often twice).
    Also rejects OpenClaw's own failure stub strings so they surface as
    errors instead of fake assistant replies.
    """
    if not isinstance(payload, dict):
        return ""
    state = str(payload.get(OC_KEY_STATE) or "").lower()
    if state in OC_STATE_ERROR:
        return ""

    msg = payload.get(OC_KEY_MESSAGE)
    role = ""
    if isinstance(msg, dict):
        role = str(msg.get("role") or "").lower()
    if role in OC_ROLE_USER_SYSTEM:
        return ""

    def _clean(s: str) -> str:
        s = (s or "").strip()
        if not s or _is_failed_assistant_stub(s) or _is_silent_reply_token(s):
            return ""
        return s

    # Prefer streaming delta fields when present.
    for key in ("deltaText", OC_KEY_TEXT):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return _clean(val)

    if not isinstance(msg, dict):
        content = payload.get(OC_KEY_CONTENT)
        if isinstance(content, str) and content and state in OC_STATE_FINAL:
            return _clean(content)
        return ""

    content = msg.get(OC_KEY_CONTENT)
    if isinstance(content, str) and content:
        return _clean(content) if role in (OC_ROLE_ASSISTANT, "") else ""
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                t = block.get(OC_KEY_TEXT) or block.get(OC_KEY_CONTENT) or ""
                if t:
                    parts.append(str(t))
            elif block:
                parts.append(str(block))
        return _clean("".join(parts))
    text = msg.get(OC_KEY_TEXT)
    return _clean(str(text)) if text else ""


async def run_openclaw_ws(
    gateway_url: str,
    gateway_token: str,
    agent_name: str,
    prompt: str,
    *,
    model: str = "",
    system_prompt: str = "",
    on_event=None,
    session_key: str = "",
    resume_session_id: str = "",
    workdir: str = "",
    stdout_log_path: Optional[str] = None,
    stderr_log_path: Optional[str] = None,
    trace_id: str = "",
    device_identity=None,
) -> StreamResult:
    """Native WS execution for OpenClaw using long-lived sessionKey for resume.

    This gives true native resume like CLI agents (claude --resume):
    - The stable sessionKey (derived from agent+scope) is the long-lived
      handle on the OpenClaw side. Prior turns stay in the runner's thread
      (warm KV cache, full prior context).
    - On resume turns (resume_session_id present), we send *only* the new
      user prompt under that sessionKey. No full history rebuild, no
      re-sending the (potentially large) system prompt every turn.
    - System prompt + Agentira layering is sent only on the first turn for
      a given sessionKey (when no prior resume id).
    """
    result = StreamResult()
    if not gateway_url:
        result.error = "missing gateway_url"
        result.success = False
        return result

    stdout_log_f = None
    stderr_log_f = None
    if stdout_log_path:
        try:
            os.makedirs(os.path.dirname(stdout_log_path), exist_ok=True)
            stdout_log_f = open(stdout_log_path, "ab", buffering=0)
        except OSError as exc:
            logger.warning("stdout log open failed (%s): %s", stdout_log_path, exc)
    if stderr_log_path:
        try:
            os.makedirs(os.path.dirname(stderr_log_path), exist_ok=True)
            stderr_log_f = open(stderr_log_path, "ab", buffering=0)
        except OSError as exc:
            logger.warning("stderr log open failed (%s): %s", stderr_log_path, exc)

    ws_base = gateway_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    # Prefer device token for execution auth; shared gateway token is registration-only.
    auth_token = ""
    auth_kind = "token"
    if device_identity is not None and getattr(device_identity, "device_token", ""):
        auth_token = device_identity.device_token
        auth_kind = "deviceToken"
    elif gateway_token:
        auth_token = gateway_token
        auth_kind = "token"
    ws_url = f"{ws_base}/?auth.token={auth_token}" if auth_token else ws_base

    is_resume = bool(resume_session_id)
    messages: list[dict] = []
    if system_prompt and not is_resume:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # session_key must already be agent:ar-<id>:<scope> (OpenClawRuntime).
    # workdir is bound onto that engine agent before this call; recorded for logs.
    if workdir:
        logger.debug(
            "openclaw ws turn workdir=%s sessionKey=%s trace=%s",
            workdir, session_key or resume_session_id, trace_id,
        )

    ev_queue: queue.Queue = queue.Queue()
    stop = threading.Event()

    collected_text: list[str] = []
    usage: dict = {}
    # Cumulative assistant text already streamed — used to convert OpenClaw
    # full-message rebroadcasts into true deltas (one growing bubble).
    streamed_so_far = ""
    # Dedup tool frames: tool-events cap delivers event:"agent", and
    # sessions.subscribe also delivers event:"session.tool" for the same call.
    seen_tool_keys: set[str] = set()

    def _ws_main() -> None:
        nonlocal streamed_so_far
        ws = None
        try:
            import websocket  # type: ignore
        except Exception as exc:
            ev_queue.put({"_fatal": f"websocket package unavailable: {exc}"})
            return

        try:
            # suppress_origin: OpenClaw refuses silent local pairing when a
            # browser Origin header is present (websocket-client default).
            ws = websocket.create_connection(
                ws_url, timeout=45, suppress_origin=True,
            )

            # 1. challenge
            try:
                ch = json.loads(ws.recv())
            except Exception:
                ch = {}
            nonce = ""
            if isinstance(ch, dict) and ch.get("event") == OC_EVENT_CONNECT_CHALLENGE:
                nonce = (ch.get("payload") or {}).get("nonce") or ""

            # 2. connect — device-token auth when registered; signed device keeps scopes
            connect_kwargs: dict = {
                "user_agent": "agentira-daemon",
                "auth_kind": auth_kind,
                "display_name": "agentira-daemon",
            }
            if device_identity is not None and nonce:
                try:
                    from agentira_cli.runtimes.openclaw_device import (
                        EXEC_CLIENT_ID,
                        EXEC_CLIENT_MODE,
                        build_device_connect_field,
                    )
                    from agentira_cli.runtimes.openclaw_scopes import default_requested_scopes

                    scopes = list(getattr(device_identity, "scopes", None) or default_requested_scopes())
                    connect_kwargs["device"] = build_device_connect_field(
                        identity=device_identity,
                        client_id=EXEC_CLIENT_ID,
                        client_mode=EXEC_CLIENT_MODE,
                        role="operator",
                        scopes=scopes,
                        token=auth_token,
                        nonce=nonce,
                        platform=__import__("platform").system().lower() or "unknown",
                    )
                    connect_kwargs["scopes"] = scopes
                    connect_kwargs["client_id"] = EXEC_CLIENT_ID
                    connect_kwargs["client_mode"] = EXEC_CLIENT_MODE
                except Exception as exc:
                    logger.warning("openclaw device sign failed: %s", exc)

            ws.send(
                json.dumps(
                    {
                        "type": "req",
                        "id": "c1",
                        "method": OC_RPC_CONNECT,
                        "params": build_connect_params(auth_token, **connect_kwargs),
                    }
                )
            )
            hello = json.loads(ws.recv())
            if not hello.get("ok"):
                err = hello.get("error") or hello
                msg = err if isinstance(err, str) else (err.get("message") if isinstance(err, dict) else str(err))
                if isinstance(msg, str) and "operator.write" in msg:
                    err = {
                        "code": (err.get("code") if isinstance(err, dict) else "INVALID_REQUEST"),
                        "message": (
                            f"{msg}. Daemon OpenClaw device lacks operator.write. "
                            "Run: agentira daemon pair && agentira daemon restart. "
                            "Check: openclaw devices list"
                        ),
                    }
                ev_queue.put({"_fatal": err})
                return

            # 3. subscribe for tool + transcript events (best-effort).
            # OpenClaw has two registries:
            #   sessions.subscribe        → sessionEventSubscribers → session.tool
            #   sessions.messages.subscribe → sessionMessageSubscribers → chat msgs
            # Tool frames also arrive as agent + stream=tool when we connect with
            # caps tool-events (registered on chat.send).
            # OpenClaw schema uses `key`, not `sessionKey`, for messages.subscribe.
            skey = session_key or resume_session_id
            for sub_id, method, params in (
                ("sub0", OC_RPC_SESSIONS_SUBSCRIBE, {}),
                (
                    "sub1",
                    OC_RPC_SESSIONS_MESSAGES_SUBSCRIBE,
                    {"key": skey} if skey else None,
                ),
            ):
                if params is None:
                    continue
                try:
                    ws.send(
                        json.dumps(
                            {
                                "type": "req",
                                "id": sub_id,
                                "method": method,
                                "params": params,
                            }
                        )
                    )
                    _ = ws.recv()  # ack, ignore shape
                except Exception:
                    pass

            # 4. send the turn via chat.send (requires operator.write).
            import uuid as _uuid
            send_id = "s1"
            turn_key = skey or session_key or resume_session_id
            # OpenClaw's channel/WebChat path teaches the model to answer
            # NO_REPLY when it thinks silence is fine. Agentira always needs
            # a user-visible reply — forbid the silence token.
            _anti_silence = (
                "You are answering inside Agentira Forge chat. "
                "Always reply with a real, helpful answer to the user. "
                "Never reply with only NO_REPLY, NO, or HEARTBEAT_OK."
            )
            body = prompt
            if system_prompt and not is_resume:
                body = f"{_anti_silence}\n\n{system_prompt}\n\n{prompt}"
            elif not is_resume:
                body = f"{_anti_silence}\n\n{prompt}"
            else:
                # Resume turns still need the anti-silence nudge — OpenClaw
                # keeps channel silence training on the thread.
                body = f"{_anti_silence}\n\n{prompt}"
            if not turn_key:
                run_error = (
                    "OpenClaw sessionKey missing — engine agent routing "
                    "requires agent:ar-<id>:<scope>"
                )
                ev_queue.put({"_fatal": run_error})
                return
            send_params: dict = {
                "sessionKey": turn_key,
                "message": body,
                "idempotencyKey": str(_uuid.uuid4()),
            }

            ws.send(
                json.dumps(
                    {
                        "type": "req",
                        "id": send_id,
                        "method": OC_RPC_CHAT_SEND,
                        "params": send_params,
                    }
                )
            )

            # 5. drain res + events until terminal success/error.
            run_error = ""
            for _ in range(4000):  # safety for very long runs
                if stop.is_set():
                    break
                try:
                    if hasattr(ws, "settimeout"):
                        try:
                            ws.settimeout(90)
                        except Exception:
                            pass
                    raw = ws.recv()
                except Exception as exc:
                    if not collected_text and not run_error:
                        run_error = _format_openclaw_error(
                            f"OpenClaw stopped responding ({exc})"
                        )
                    break
                if not raw:
                    break
                try:
                    f = json.loads(raw)
                except Exception:
                    continue

                if f.get("type") == "res" and f.get("id") == send_id:
                    if not f.get("ok"):
                        run_error = _format_openclaw_error(f.get("error") or f)
                        ev_queue.put({"_fatal": run_error})
                        break
                    pl = f.get("payload") or {}
                    if isinstance(pl, dict):
                        if pl.get("usage"):
                            usage.update(pl["usage"])
                        if pl.get("content"):
                            content = str(pl["content"])
                            streamed_so_far, delta, _repl = _snapshot_to_delta(
                                streamed_so_far, content,
                            )
                            if delta:
                                collected_text.append(delta)
                    # continue draining events after the ack

                elif f.get("type") == "event":
                    ename = f.get("event", "")
                    p = f.get("payload") or {}
                    if not isinstance(p, dict):
                        p = {}

                    # Terminal model/runtime failure from OpenClaw.
                    chat_err = (
                        _extract_chat_error(p) if ename in OC_ERROR_EVENTS else ""
                    )
                    if not chat_err and ename in ("agent.error", "run.error", "error"):
                        chat_err = _format_openclaw_error(p or f)
                    # Failure stubs sometimes land as "assistant" content.
                    if not chat_err and ename in (
                        OC_EVENT_CHAT, "chat.message", "message",
                    ):
                        msg0 = (
                            p.get(OC_KEY_MESSAGE)
                            if isinstance(p.get(OC_KEY_MESSAGE), dict)
                            else {}
                        )
                        stub = ""
                        if isinstance(msg0, dict):
                            c = msg0.get(OC_KEY_CONTENT)
                            if isinstance(c, str):
                                stub = c
                            elif isinstance(c, list):
                                stub = " ".join(
                                    str(b.get(OC_KEY_TEXT) or "")
                                    if isinstance(b, dict) else str(b)
                                    for b in c
                                )
                        if _is_failed_assistant_stub(stub) or _is_failed_assistant_stub(
                            str(p.get(OC_KEY_TEXT) or "")
                        ):
                            chat_err = _format_openclaw_error(stub or p)
                    if chat_err:
                        run_error = chat_err
                        # Stream a short error line so the chat UI unsticks.
                        ev_queue.put({
                            "type": EVT_TEXT,
                            "text": chat_err,
                            "model": p.get(OC_KEY_MODEL, ""),
                        })
                        ev_queue.put({"_fatal": chat_err})
                        break

                    # text / delta (assistant only — never echo user role)
                    if ename in OC_CHAT_EVENTS:
                        state = str(p.get(OC_KEY_STATE) or "").lower()
                        msg = (
                            p.get(OC_KEY_MESSAGE)
                            if isinstance(p.get(OC_KEY_MESSAGE), dict)
                            else {}
                        )
                        role = str((msg or {}).get("role") or "").lower()
                        # Detect silence tokens *before* stripping them out.
                        raw_assist = ""
                        if isinstance(msg, dict):
                            c = msg.get(OC_KEY_CONTENT)
                            if isinstance(c, str):
                                raw_assist = c
                            elif isinstance(c, list):
                                raw_assist = "".join(
                                    str(b.get(OC_KEY_TEXT) or "")
                                    if isinstance(b, dict) else str(b)
                                    for b in c
                                )
                            elif msg.get(OC_KEY_TEXT):
                                raw_assist = str(msg.get(OC_KEY_TEXT))
                        if not raw_assist and isinstance(p.get(OC_KEY_TEXT), str):
                            raw_assist = p[OC_KEY_TEXT]
                        if role == OC_ROLE_ASSISTANT and _is_silent_reply_token(raw_assist):
                            run_error = (
                                "OpenClaw returned NO_REPLY (silence). The model "
                                "chose not to answer. Ask a clearer question."
                            )
                            ev_queue.put({"_fatal": run_error})
                            break
                        snapshot = _assistant_text_from_chat_payload(p)
                        delta = ""
                        replace = False
                        if snapshot:
                            streamed_so_far, delta, replace = _snapshot_to_delta(
                                streamed_so_far, snapshot,
                            )
                        if delta:
                            ev: dict = {
                                "type": EVT_TEXT,
                                "text": delta,
                                "model": p.get(OC_KEY_MODEL, ""),
                            }
                            if replace:
                                # Full rewrite — backend must replace, not append.
                                ev["replace"] = True
                                collected_text.clear()
                            ev_queue.put(ev)
                            collected_text.append(delta)
                        # Only end on final *assistant* frames. OpenClaw also
                        # emits final user echoes — breaking there dropped the
                        # real reply.
                        if state in OC_STATE_FINAL:
                            if role in OC_ROLE_USER_SYSTEM:
                                continue
                            if role == OC_ROLE_ASSISTANT or delta or streamed_so_far:
                                break

                    # tool lifecycle — agent/session.tool + nested data.phase.
                    # Reset cumulative text so post-tool narration is a fresh
                    # segment (not a "rewrite" of pre-tool prose).
                    else:
                        for tev in _tool_wire_events(ename, p):
                            dedupe = (
                                f"{tev.get('type')}: "
                                f"{tev.get(EVT_TOOL_CALL_ID) or ''}:"
                                f"{tev.get('tool') or ''}"
                            )
                            if dedupe in seen_tool_keys:
                                continue
                            seen_tool_keys.add(dedupe)
                            streamed_so_far = ""
                            collected_text.clear()
                            ev_queue.put(tev)

                    if ename in OC_COMPLETE_EVENTS:
                        if not run_error:
                            run_error = _extract_chat_error(p)
                        break

            result.text = (streamed_so_far or "".join(collected_text)).strip()
            if result.text and _is_silent_reply_token(result.text):
                run_error = run_error or (
                    "OpenClaw returned NO_REPLY (silence). The model chose not "
                    "to answer — retry with a clearer question."
                )
                result.text = ""
            if run_error and not result.error:
                result.error = run_error
                result.success = False
            else:
                result.success = bool(result.text) and not run_error
            result.session_id = (session_key or resume_session_id or "")
            if usage:
                result.input_tokens = int(usage.get("prompt_tokens", usage.get("inputTokens", 0)) or 0)
                result.output_tokens = int(usage.get("completion_tokens", usage.get("outputTokens", 0)) or 0)

        except Exception as exc:
            result.error = _format_openclaw_error(exc) or str(exc)
            result.success = False
            logger.warning("openclaw native ws error trace=internal: %s", exc)
        finally:
            stop.set()
            ev_queue.put(None)
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    t = threading.Thread(target=_ws_main, daemon=True)
    t.start()

    batch: list = []
    last = time.monotonic()

    async def _flush() -> None:
        nonlocal batch, last
        if batch and on_event:
            try:
                await on_event(list(batch))
            except Exception as exc:
                logger.warning("openclaw on_event error: %s", exc)
        batch = []
        last = time.monotonic()

    while True:
        try:
            item = ev_queue.get(timeout=0.15)
        except queue.Empty:
            if not t.is_alive():
                break
            if time.monotonic() - last >= 0.5:
                await _flush()
            continue

        if item is None:
            break
        if "_fatal" in item:
            result.error = _format_openclaw_error(item["_fatal"]) or str(item["_fatal"])
            result.success = False
            break

        batch.append(item)
        _tee_json_line(stdout_log_f, item)
        if time.monotonic() - last >= 0.5:
            await _flush()

    await _flush()
    t.join(timeout=3.0)

    if not result.success and not result.error:
        result.error = (
            "OpenClaw produced no reply. Check that OpenClaw is running and "
            "its model provider (e.g. Ollama) is up."
        )
    if result.error:
        result.error = _format_openclaw_error(result.error) or result.error
        result.success = False
    if not result.success and result.error:
        _tee_stderr(stderr_log_f, result.error, trace_id=trace_id)

    for f in (stdout_log_f, stderr_log_f):
        if f is not None:
            try:
                f.close()
            except OSError:
                pass
    return result
