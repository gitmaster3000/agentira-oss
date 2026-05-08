"""Stream-JSON executor — spawns a CLI runtime, drains output, batches events to backend.

Replaces the blocking subprocess.run in core.py for claude/codex runtimes.
Ported from multica/server/pkg/agent/claude.go + daemon.go:1426-1510.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import urllib.request
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
    max_turns: int = 20,
    system_prompt: str = "",
    mcp_config_json: Optional[str] = None,
    resume_session_id: str = "",
    workdir: Optional[str] = None,
    env_extra: Optional[dict] = None,
    on_event=None,        # async callable(event_list) for batching to backend
    on_proc=None,         # called with the spawned proc (and again with None on exit) so callers can kill() externally
) -> StreamResult:
    """Spawn a CLI runtime with stream-json I/O; drain stdout line-by-line; return StreamResult."""
    result = StreamResult()
    mcp_config_path = ""

    try:
        if mcp_config_json:
            mcp_config_path = _write_mcp_config(mcp_config_json)

        args = runtime_cls.build_args(
            prompt,
            model=model,
            max_turns=max_turns,
            system_prompt=system_prompt,
            mcp_config_path=mcp_config_path,
            resume_session_id=resume_session_id,
        )

        env = _build_env(env_extra or {})

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
        )
        # Hand the proc up so the caller can kill() us on cancel.
        if on_proc:
            try:
                on_proc(proc)
            except Exception:
                pass

        batch: list = []
        last_flush = time.monotonic()

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
            line = raw_line.decode(errors="replace")
            event = runtime_cls.parse_event(line)
            if event is None:
                continue

            if isinstance(event, SessionEvent) and not result.session_id:
                result.session_id = event.session_id
                logger.debug("Session ID: %s", result.session_id)

            elif isinstance(event, ResultEvent):
                result.success = event.success
                result.text = event.text
                result.error = event.error
                result.input_tokens += event.input_tokens
                result.output_tokens += event.output_tokens

            elif isinstance(event, TextEvent):
                batch.append({"type": "text", "text": event.text, "model": event.model})

            elif isinstance(event, ToolUseEvent):
                batch.append({"type": "tool_use", "tool": event.tool_name, "input": event.tool_input})

            elif isinstance(event, ToolResultEvent):
                batch.append({"type": "tool_result", "tool": event.tool_name, "output": event.output})

            # flush batch every 500ms
            if time.monotonic() - last_flush >= _BATCH_INTERVAL:
                await flush()

        await flush()
        await proc.wait()

        if proc.returncode != 0 and not result.text:
            stderr = await proc.stderr.read()
            result.error = stderr.decode(errors="replace").strip()
            result.success = False

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
) -> StreamResult:
    """POST prompt to an OpenAI-compatible HTTP gateway (e.g. openclaw).

    Mirrors backend/forge/runtime_client.py:OpenClawAdapter.chat — must stay
    in sync with that adapter so chat works identically from either side.
    Non-streaming: full request → single text event with the reply.
    """
    result = StreamResult()
    url = gateway_url.rstrip("/") + "/v1/chat/completions"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({
        "model": f"openclaw:{agent_name}",
        "messages": messages,
        "stream": False,
    }).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {gateway_token}",
    }
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
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


def _write_mcp_config(config_json: str) -> str:
    """Write MCP config JSON to a temp file and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="agentira-mcp-", delete=False
    ) as f:
        f.write(config_json)
        return f.name


def _build_env(extra: dict) -> dict:
    """Build subprocess environment: current env + injected vars, filtered."""
    _BLOCKED = {"AGENTIRA_DAEMON_API_KEY"}
    env = {k: v for k, v in os.environ.items() if k not in _BLOCKED}
    env.update(extra)
    return env
