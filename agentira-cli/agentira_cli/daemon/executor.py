"""Stream-JSON executor — spawns a CLI runtime, drains output, batches events to backend.

Replaces the blocking subprocess.run in core.py for claude/codex runtimes.
Ported from multica/server/pkg/agent/claude.go + daemon.go:1426-1510.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Optional

from agentira_cli.runtimes.claude import (
    ResultEvent,
    SessionEvent,
    TextEvent,
    ToolResultEvent,
    ToolUseEvent,
)

logger = logging.getLogger("agentira.daemon.executor")

_BATCH_INTERVAL = 0.5  # seconds between event flushes
_CRASH_TAIL_EVENTS = 8  # how many trailing stream events to keep for diagnostics

# HTTP gateway (ollama and similar) chat-completions timeout. Local models
# can take minutes; env-overridable.
_GATEWAY_TIMEOUT_S = int(os.environ.get("AGENTIRA_GATEWAY_TIMEOUT", "600"))


def _derive_allowed_tools(mcp_config_json: Optional[str], provider: str) -> tuple[str, ...]:
    """AP-83 Path A — assemble the explicit tool allowlist for this dispatch.

    Returns a tuple of tool names suitable for claude-code's --allowedTools:
    the runtime's stable builtins (Read, Edit, Bash, …) plus a `mcp__<server>`
    wildcard for every MCP server in the dispatch config. Other providers
    return an empty tuple — only claude consumes this today.

    Empty tuple means "do not emit --allowedTools at all" so behavior is
    unchanged when no MCP servers are configured AND the provider has no
    builtins on file.
    """
    if provider != "claude":
        return ()
    # Stable claude-code builtins. Kept in sync with daemon.host_tools.
    builtins: list[str] = [
        "Read", "Edit", "Write", "Bash", "Grep", "Glob",
        "WebFetch", "WebSearch", "Task", "TodoWrite",
        "NotebookEdit", "BashOutput", "KillShell",
    ]
    servers: list[str] = []
    if mcp_config_json:
        try:
            cfg = json.loads(mcp_config_json)
            for name in (cfg.get("mcpServers") or {}).keys():
                servers.append(f"mcp__{name}")
        except (TypeError, ValueError):
            pass
    return tuple(builtins + servers)


def _crash_tail(recent) -> str:
    """Render the last few stream events as human-readable crash context.

    When a runtime exits non-zero with no stderr and no result frame, the
    bare "subprocess exited with code 1" is useless. This appends what the
    agent was actually doing in its final moments so the failure is
    diagnosable from the run's error field alone.
    """
    if not recent:
        return "No stream events were received before the exit."
    lines = []
    for ev in recent:
        t = ev.get("type")
        if t == "text":
            s = (ev.get("text") or "").strip().replace("\n", " ")
            if s:
                lines.append(f"  · assistant: {s[:160]}")
        elif t == "tool_use":
            inp = str(ev.get("input") or "").replace("\n", " ")
            lines.append(f"  · tool {ev.get('tool')}({inp[:160]})")
        elif t == "tool_result":
            out = str(ev.get("output") or "").strip().replace("\n", " ")
            lines.append(f"  · tool {ev.get('tool')} → {out[:200]}")
    return "Last activity before exit:\n" + "\n".join(lines)


class StreamResult:
    def __init__(self):
        self.success = False
        self.text = ""
        self.error = ""
        self.session_id: Optional[str] = None
        self.input_tokens = 0
        self.output_tokens = 0


async def run_cli_stream(
    runtime_cls,
    binary_path: str,
    prompt: str,
    *,
    model: str = "",
    max_turns: int = 300,
    system_prompt: str = "",
    mcp_config_json: Optional[str] = None,
    mcp_strict: bool = False,
    resume_session_id: str = "",
    workdir: Optional[str] = None,
    env_extra: Optional[dict] = None,
    env_strip: Optional[set] = None,   # AP-308: hermetic — drop these inherited vars
    on_event=None,        # async callable(event_list) for batching to backend
    on_proc=None,         # called with the spawned proc (and again with None on exit) so callers can kill() externally
    # Per-run log files. When set, every byte of stdout / stderr is
    # tee'd to disk (append, line-buffered) so the run is debuggable
    # in isolation even on daemon restart. Best-effort: I/O errors are
    # logged and the run keeps going.
    stdout_log_path: Optional[str] = None,
    stderr_log_path: Optional[str] = None,
) -> StreamResult:
    """Spawn a CLI runtime with stream-json I/O; drain stdout line-by-line; return StreamResult."""
    result = StreamResult()
    mcp_config_path = ""

    try:
        if mcp_config_json:
            mcp_config_path = _write_mcp_config(mcp_config_json)
            # Preflight HTTP MCP servers. If a URL is unreachable from the
            # daemon host (common deploy bug: backend baked an internal
            # docker hostname into the config), claude-code silently
            # drops the server and the agent says "those tools aren't
            # available." Surface that loudly here so the user sees what
            # broke instead of debugging blind.
            warnings = _preflight_mcp_http(mcp_config_json)
            if warnings and on_event:
                try:
                    await on_event([TextEvent(text=w) for w in warnings])
                except Exception as exc:  # noqa: BLE001 — best-effort
                    logger.debug("preflight emit failed: %s", exc)
            for w in warnings:
                logger.warning("%s", w)

        allowed_tools = _derive_allowed_tools(
            mcp_config_json, getattr(runtime_cls, "provider", ""),
        )
        args = runtime_cls.build_args(
            prompt,
            model=model,
            max_turns=max_turns,
            system_prompt=system_prompt,
            mcp_config_path=mcp_config_path,
            mcp_strict=mcp_strict,
            resume_session_id=resume_session_id,
            allowed_tools=allowed_tools,
        )

        env = _build_env(env_extra or {}, strip=env_strip)

        # Stream-json lines from claude can exceed asyncio's default 64KB
        # readline limit (single tool_result with a big diff, e.g.). Bump
        # to 10MB to match multica's bufio scanner.
        proc = await asyncio.create_subprocess_exec(
            binary_path, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
            env=env,
            limit=10 * 1024 * 1024,
            # P5: spawn claude as a session/process-group leader. Without
            # this, claude inherits the daemon's group and SIGTERM hits
            # only claude — any bash-backgrounded child (`vite dev`,
            # `pytest &`, watchers) is reparented to init and survives.
            # With it, cancel/pause uses os.killpg(claude.pid, ...) to
            # take down the whole group. Detached daemon-managed children
            # (`docker run -d`, systemd) still escape — that's deferred
            # to AP-83 Path B (container isolation).
            start_new_session=True,
        )
        # Hand the proc up so the caller can kill() us on cancel.
        if on_proc:
            try:
                on_proc(proc)
            except Exception:
                pass

        batch: list = []
        # Rolling tail of the most recent events — kept across flushes so a
        # silent crash can be diagnosed (see _crash_tail).
        recent: deque = deque(maxlen=_CRASH_TAIL_EVENTS)
        last_flush = time.monotonic()
        # Track whether the runtime ever emitted a final ResultEvent. If
        # not, the subprocess died without telling us what happened —
        # treat that as failure regardless of returncode (claude-code
        # has been observed to exit 0 after rejecting an unentitled
        # model string, which would otherwise look like silent success).
        saw_result_event = False
        # Per-run tee'd log files. Opened in unbuffered binary mode so a
        # crashed daemon doesn't lose recent bytes; closed in the finally
        # block below.
        stdout_log_f = None
        stderr_log_f = None
        if stdout_log_path:
            try:
                os.makedirs(os.path.dirname(stdout_log_path), exist_ok=True)
                stdout_log_f = open(stdout_log_path, "ab", buffering=0)
            except OSError as exc:
                logger.warning("stdout log open failed (%s): %s",
                               stdout_log_path, exc)
        if stderr_log_path:
            try:
                os.makedirs(os.path.dirname(stderr_log_path), exist_ok=True)
                stderr_log_f = open(stderr_log_path, "ab", buffering=0)
            except OSError as exc:
                logger.warning("stderr log open failed (%s): %s",
                               stderr_log_path, exc)

        # Drain stderr concurrently. If we only read it on failure we
        # risk a PIPE-buffer deadlock on chatty runtimes, AND we miss
        # the human-readable error message on the no-ResultEvent path.
        stderr_chunks: list[bytes] = []

        async def _drain_stderr():
            try:
                while True:
                    chunk = await proc.stderr.read(8192)
                    if not chunk:
                        break
                    stderr_chunks.append(chunk)
                    if stderr_log_f is not None:
                        try:
                            stderr_log_f.write(chunk)
                        except OSError:
                            pass
            except Exception as exc:  # noqa: BLE001 — best-effort
                logger.debug("stderr drain error: %s", exc)

        stderr_task = asyncio.create_task(_drain_stderr())

        async def flush():
            nonlocal batch, last_flush
            if batch and on_event:
                try:
                    await on_event(list(batch))
                except Exception as exc:
                    logger.warning("Event flush error: %s", exc)
            batch = []
            last_flush = time.monotonic()

        async for raw_line in proc.stdout:
            if stdout_log_f is not None:
                try:
                    stdout_log_f.write(raw_line)
                except OSError:
                    pass
            line = raw_line.decode(errors="replace")
            event = runtime_cls.parse_event(line)
            if event is None:
                continue

            if isinstance(event, SessionEvent) and not result.session_id:
                result.session_id = event.session_id
                logger.debug("Session ID: %s", result.session_id)

            elif isinstance(event, ResultEvent):
                saw_result_event = True
                result.success = event.success
                result.text = event.text
                result.error = event.error
                result.input_tokens += event.input_tokens
                result.output_tokens += event.output_tokens

            elif isinstance(event, TextEvent):
                ev = {"type": "text", "text": event.text, "model": event.model}
                batch.append(ev)
                recent.append(ev)

            elif isinstance(event, ToolUseEvent):
                ev = {"type": "tool_use", "tool": event.tool_name, "input": event.tool_input}
                batch.append(ev)
                recent.append(ev)

            elif isinstance(event, ToolResultEvent):
                ev = {"type": "tool_result", "tool": event.tool_name, "output": event.output}
                batch.append(ev)
                recent.append(ev)

            # flush batch every 500ms
            if time.monotonic() - last_flush >= _BATCH_INTERVAL:
                await flush()

        await flush()
        await proc.wait()
        # Make sure the stderr drain has finished before we read its
        # accumulator. proc.wait() returning means stdout closed; stderr
        # should follow quickly. Bound the wait so a stuck pipe doesn't
        # hang us forever.
        try:
            await asyncio.wait_for(stderr_task, timeout=2.0)
        except asyncio.TimeoutError:
            stderr_task.cancel()

        stderr_text = b"".join(stderr_chunks).decode(errors="replace").strip()
        # Tail the stderr so a crash dump doesn't blow up the run row.
        # 4KB is enough to read a stack trace + the actionable line.
        if len(stderr_text) > 4000:
            stderr_text = "…" + stderr_text[-4000:]

        # Decide success/error. Three failure modes:
        #   1. proc.returncode != 0 — clear-cut crash/rejection.
        #   2. proc.returncode == 0 but no ResultEvent ever arrived —
        #      runtime exited cleanly without telling us anything.
        #      claude-code does this on model-string rejection.
        #   3. ResultEvent itself reported failure (already in result.success).
        if proc.returncode != 0:
            result.success = False
            if not result.error:
                # No ResultEvent error and (often) no stderr — a silent
                # crash. Attach the event tail so the failure is
                # diagnosable from the run's error field alone.
                base = stderr_text or f"subprocess exited with code {proc.returncode}"
                result.error = f"{base}\n\n{_crash_tail(recent)}"
                logger.warning("Runtime exited code=%s stderr=%s — %s",
                                proc.returncode, bool(stderr_text),
                                _crash_tail(recent).replace("\n", " | "))
            elif stderr_text and stderr_text not in result.error:
                # Append stderr context so we don't lose the actionable
                # human-readable message when ResultEvent gave us a
                # generic error.
                result.error = f"{result.error}\n\n{stderr_text}"
        elif not saw_result_event:
            result.success = False
            base = (stderr_text
                    or "subprocess exited cleanly without emitting a result frame")
            result.error = f"{base}\n\n{_crash_tail(recent)}"
            logger.warning("Runtime exited with no result frame — %s",
                            _crash_tail(recent).replace("\n", " | "))

    finally:
        if on_proc:
            try:
                on_proc(None)
            except Exception:
                pass
        if mcp_config_path:
            try:
                os.unlink(mcp_config_path)
            except OSError:
                pass
        # Close per-run log files. Guarded — they may not have opened
        # successfully (caller passed paths, but OSError on open landed
        # both at None).
        for f in (stdout_log_f, stderr_log_f):
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass

    return result


# Keep the old name as an alias so any remaining callers don't break immediately.
async def run_claude_stream(binary_path, prompt, **kwargs):
    from agentira_cli.runtimes.claude import ClaudeRuntime
    return await run_cli_stream(ClaudeRuntime, binary_path, prompt, **kwargs)


async def run_gateway(
    gateway_url: str,
    gateway_token: str,
    agent_name: str,
    prompt: str,
    *,
    model: str = "",
    system_prompt: str = "",
    on_event=None,
    provider: str = "openclaw",
    session_key: str = "",
) -> StreamResult:
    """POST prompt to an OpenAI-compatible HTTP gateway.

    Used by ollama and other http-only gateways. OpenClaw now uses the
    native WS path (run_openclaw_ws) so we get real streaming events.
    """
    result = StreamResult()
    url = gateway_url.rstrip("/") + "/v1/chat/completions"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # Pick the model string the gateway expects.
    if provider == "openclaw":
        body_model = "openclaw:agentira-runner"
    elif provider == "ollama":
        # Strip the `ollama/` prefix Agentira surfaces internally so Ollama's
        # OpenAI-compatible endpoint sees the bare model id.
        body_model = (model or "").split("ollama/", 1)[-1] if model else ""
    else:
        body_model = model or agent_name

    body = json.dumps({
        "model": body_model,
        "messages": messages,
        "stream": False,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if gateway_token:
        headers["Authorization"] = f"Bearer {gateway_token}"
    # ADR 009 / Runtime Adapter contract: OpenClaw routes per-turn session
    # via the `x-openclaw-session-key` header (per OpenClaw's
    # docs/gateway/openai-http-api.md). One key per (agent, scope) gives
    # us a server-side thread with the KV cache warm across turns.
    if session_key and provider == "openclaw":
        headers["x-openclaw-session-key"] = session_key
        # Round-trip the key as the captured session_id so the backend
        # stores it on forge_conversations.runtime_session_id and replays
        # it on the next dispatch (parity with claude's session_id flow).
        result.session_id = session_key
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=_GATEWAY_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
        choices = data.get("choices") or []
        content = ""
        if choices:
            content = choices[0].get("message", {}).get("content", "") or ""
        usage = data.get("usage") or {}
        result.success = bool(content)
        result.text = content
        result.input_tokens = usage.get("prompt_tokens", 0)
        result.output_tokens = usage.get("completion_tokens", 0)
        if not result.success:
            result.error = "Empty response from gateway"
        if on_event and content:
            await on_event([{"type": "text", "text": content, "model": data.get("model", "")}])
    except Exception as exc:
        result.error = str(exc)
        result.success = False
        logger.warning("Gateway request failed: %s", exc)
    return result


def _preflight_mcp_http(config_json: str) -> list[str]:
    """Probe every HTTP MCP server in the config from the daemon host.

    Returns a list of human-readable warning strings — one per server
    that failed to respond. Connection errors (DNS, refused, timeout)
    are the real signal: these mean the URL baked into the config isn't
    reachable from where claude-code will dial it. 4xx/5xx are NOT
    flagged — auth failures (401) and method-not-allowed (405) just
    confirm the server is up. We only care about transport-level
    failures here.
    """
    out: list[str] = []
    try:
        cfg = json.loads(config_json) if config_json else {}
    except Exception as exc:  # noqa: BLE001
        return [f"⚠ MCP preflight: config JSON parse failed — {exc}"]
    for name, entry in (cfg.get("mcpServers") or {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "http":
            continue  # stdio servers spawn locally; nothing to probe
        url = entry.get("url") or ""
        if not url:
            continue
        try:
            req = urllib.request.Request(url, method="GET")
            # Carry the auth header so servers that gate everything still
            # answer (won't matter for transport-failure detection but
            # avoids confusing logs).
            for hk, hv in (entry.get("headers") or {}).items():
                req.add_header(hk, hv)
            with urllib.request.urlopen(req, timeout=3) as resp:
                _ = resp.status  # any HTTP response = reachable
        except urllib.error.HTTPError:
            # Server answered with an error code — that's fine, it's UP.
            pass
        except Exception as exc:  # noqa: BLE001 — DNS, refused, timeout, etc.
            out.append(
                f"⚠ MCP server '{name}' unreachable at {url} ({type(exc).__name__}: {exc}). "
                "The agent will run WITHOUT this server's tools. "
                "If the URL is an internal hostname (e.g. http://mcp:8000), "
                "set AGENTIRA_MCP_URL on the backend to a host-reachable URL."
            )
    return out


def _write_mcp_config(config_json: str) -> str:
    """Write MCP config JSON to a temp file and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="agentira-mcp-", delete=False
    ) as f:
        f.write(config_json)
        return f.name


def _build_env(extra: dict, strip: Optional[set] = None) -> dict:
    """Build subprocess environment: current env + injected vars, filtered.

    `strip` (AP-308 hermetic mode) drops shared-service vars from the
    inherited env so a run can't reach the developer's long-lived stack.
    Applied to the inherited env only — explicitly injected `extra` wins
    (per_run_db injects its own AGENTIRA_DB_URL there).
    """
    _BLOCKED = {"AGENTIRA_DAEMON_API_KEY"} | (strip or set())
    env = {k: v for k, v in os.environ.items() if k not in _BLOCKED}
    env.update(extra)
    return env


def _tee_json_line(log_f, obj: dict) -> None:
    """Best-effort append of one JSON line to a per-run stdout log."""
    if log_f is None:
        return
    try:
        log_f.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
    except OSError:
        pass


def _tee_stderr(log_f, msg: str, *, trace_id: str = "") -> None:
    """Best-effort append of one error line to a per-run stderr log."""
    if log_f is None:
        return
    try:
        log_f.write((f"{msg} trace={trace_id}\n").encode())
    except OSError:
        pass


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
    stdout_log_path: Optional[str] = None,
    stderr_log_path: Optional[str] = None,
    trace_id: str = "",
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
    - This is the point of advertising "resume" + using native WS: avoid the
      cost of assemble_context full history + token bloat on every turn.
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
    ws_url = f"{ws_base}/?auth.token={gateway_token}" if gateway_token else ws_base

    # === Long-lived sessionKey for native resume (like claude --resume) ===
    # The sessionKey (derived deterministically from agent+scope) is the
    # persistent thread identifier on OpenClaw under the agentira-runner.
    # When the backend passes a resume_session_id (from prior turn's
    # runtime_session_id stored in the Conversation), we treat this as a
    # continuation:
    #   - Send *only* the new user prompt (as "text").
    #   - Do NOT re-send system_prompt or any prior messages.
    # This eliminates the expensive full-history rebuild on every turn and
    # avoids bloating the wire + OpenClaw context with repeated system text.
    # System prompt (Agentira persona + conventions + memory notes) is sent
    # exactly once, on the first turn for that sessionKey.
    is_resume = bool(resume_session_id)
    messages: list[dict] = []
    if system_prompt and not is_resume:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # Runner target keeps the separation (engine from OpenClaw, persona/MCP/prompt from Agentira)
    runner_target = "agentira-runner"

    ev_queue: queue.Queue = queue.Queue()
    stop = threading.Event()

    collected_text: list[str] = []
    usage: dict = {}

    def _ws_main() -> None:
        ws = None
        try:
            import websocket  # type: ignore
        except Exception as exc:
            ev_queue.put({"_fatal": f"websocket package unavailable: {exc}"})
            return

        try:
            ws = websocket.create_connection(ws_url, timeout=45)

            # 1. challenge
            try:
                ch = json.loads(ws.recv())
            except Exception:
                ch = {}

            # 2. connect (protocol v4)
            ws.send(
                json.dumps(
                    {
                        "type": "req",
                        "id": "c1",
                        "method": "connect",
                        "params": {
                            "minProtocol": 4,
                            "maxProtocol": 4,
                            "client": {
                                "id": "agentira-daemon",
                                "version": "2026.7",
                                "platform": "macos",
                                "mode": "operator",
                            },
                            "role": "operator",
                            "scopes": ["operator.read", "operator.write"],
                            "caps": ["tool-events"],
                            "commands": [],
                            "permissions": {},
                            "auth": {"token": gateway_token} if gateway_token else {},
                            "locale": "en-US",
                            "userAgent": "agentira-daemon/1.0",
                        },
                    }
                )
            )
            hello = json.loads(ws.recv())
            if not hello.get("ok"):
                ev_queue.put({"_fatal": hello.get("error") or hello})
                return

            # 3. subscribe for transcript events on our session (best-effort)
            skey = session_key or resume_session_id
            if skey:
                try:
                    ws.send(
                        json.dumps(
                            {
                                "type": "req",
                                "id": "sub1",
                                "method": "sessions.messages.subscribe",
                                "params": {"sessionKey": skey},
                            }
                        )
                    )
                    _ = ws.recv()  # ack, ignore shape
                except Exception:
                    pass

            # 4. send the turn — use long-lived sessionKey + minimal payload on resume
            send_id = "s1"
            if is_resume:
                # Lightweight native resume using the long-lived sessionKey:
                # send ONLY the new user message. The entire prior conversation
                # (including the system prompt we sent on first turn) lives in
                # the OpenClaw runner thread for that sessionKey. This is the
                # equivalent of claude --resume <session> — no history rebuild.
                send_params: dict = {
                    "sessionKey": skey,
                    "messages": [{"role": "user", "content": prompt}],
                    "agentId": runner_target,
                }
            else:
                # First turn for this key: include system so Agentira layers
                # its prompt/config on the clean runner.
                send_params: dict = {
                    "sessionKey": session_key,
                    "messages": messages,
                    "agentId": runner_target,
                }

            ws.send(
                json.dumps(
                    {
                        "type": "req",
                        "id": send_id,
                        "method": "chat.send",
                        "params": send_params,
                    }
                )
            )

            # 5. drain res + events until we see terminal signal or quiet
            for _ in range(4000):  # safety for very long runs
                if stop.is_set():
                    break
                try:
                    raw = ws.recv()
                except Exception:
                    break
                if not raw:
                    break
                try:
                    f = json.loads(raw)
                except Exception:
                    continue

                if f.get("type") == "res" and f.get("id") == send_id:
                    if not f.get("ok"):
                        ev_queue.put({"_fatal": f.get("error") or f})
                        break
                    pl = f.get("payload") or {}
                    if isinstance(pl, dict):
                        if pl.get("usage"):
                            usage.update(pl["usage"])
                        if pl.get("content"):
                            collected_text.append(pl["content"])
                    # continue draining events after the ack

                elif f.get("type") == "event":
                    ename = f.get("event", "")
                    p = f.get("payload") or {}

                    # text / delta
                    if ename in ("chat", "chat.message", "session.message", "message", "chat.inject"):
                        delta = (
                            p.get("deltaText")
                            or p.get("text")
                            or (p.get("message") or {}).get("content", "")
                            or (p.get("message") or {}).get("text", "")
                            or p.get("content", "")
                        )
                        if delta:
                            ev_queue.put({"type": "text", "text": delta, "model": p.get("model", "")})
                            collected_text.append(delta)

                    # tool lifecycle (structured because we advertised tool-events)
                    elif ename in ("session.tool", "tool", "tool_use", "agent.tool"):
                        tname = p.get("name") or p.get("tool") or p.get("toolName") or ""
                        tin = p.get("input") or p.get("args") or p.get("parameters") or ""
                        if tname:
                            ev_queue.put({"type": "tool_use", "tool": tname, "input": tin})

                    elif ename in (
                        "session.tool.result",
                        "tool_result",
                        "tool.result",
                        "agent.tool_result",
                    ):
                        tname = p.get("name") or p.get("tool") or ""
                        tout = p.get("output") or p.get("result") or p.get("content") or str(p)[:2000]
                        ev_queue.put({"type": "tool_result", "tool": tname, "output": tout})

                    if ename in ("chat.complete", "session.complete", "run.finished", "chat.done"):
                        break

            result.text = "".join(collected_text).strip()
            result.success = bool(result.text)
            # The long-lived sessionKey is what the backend will store as
            # runtime_session_id and pass back as resume_session_id next time.
            result.session_id = (session_key or resume_session_id or "")
            if usage:
                result.input_tokens = int(usage.get("prompt_tokens", usage.get("inputTokens", 0)) or 0)
                result.output_tokens = int(usage.get("completion_tokens", usage.get("outputTokens", 0)) or 0)

        except Exception as exc:
            result.error = str(exc)
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

    # Async drain with batching (mirrors run_cli_stream behavior)
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
            result.error = str(item["_fatal"])
            result.success = False
            break

        batch.append(item)
        _tee_json_line(stdout_log_f, item)
        if time.monotonic() - last >= 0.5:
            await _flush()

    await _flush()
    t.join(timeout=3.0)

    if not result.success and not result.error:
        result.error = "openclaw ws: no content produced"
    if not result.success and result.error:
        _tee_stderr(stderr_log_f, result.error, trace_id=trace_id)

    for f in (stdout_log_f, stderr_log_f):
        if f is not None:
            try:
                f.close()
            except OSError:
                pass
    return result
