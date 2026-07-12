# PR: Switch OpenClaw to native WS + long-lived sessionKey for resume

## Summary
Replaced the HTTP gateway (`/v1/chat/completions` non-streaming) path for OpenClaw with its native WebSocket RPC protocol (`chat.send` + event stream over the gateway WS).

This enables:
- True incremental streaming of agent thoughts, tool calls, results (text deltas, `session.tool*` events).
- Long-lived `sessionKey` resume capability (like `claude --resume`).
- No more full conversation history rebuild + re-send on every turn.
- Reliable "running" state on board for openclaw/ollama task runs (via inflight pid=0 record + heartbeats during the WS turn).
- "One thing and stops" fixed because events now flow incrementally instead of one final completion response.

Ollama and other pure HTTP gateways remain on the old `http_gateway` + `run_gateway` path.

## Architecture preserved (critical)
We continue to use the `agentira-runner` placeholder agent in OpenClaw (configured with empty `systemPromptOverride` and full tools profile).

- OpenClaw/runner supplies the engine (MCP tools, workspace, execution).
- Agentira layers **on top** (per dispatch):
  - `system_prompt` (only on first turn for a sessionKey).
  - Per-agent MCP registration (via `register_agentira_mcps` right before connect; injects the agent's token + memory path).
  - Conversation continuity via stable `sessionKey`.
- User's personal OpenClaw agent configs / personas do **not** pollute Agentira agents.

This was explicitly kept and documented in the code.

## Long-lived sessionKey for native resume
- `derive_session_handle` produces the canonical `agentira:<agent8>:<sanitized-scope>` key.
- On first turn for a scope: derive (or use provided) key, send system + user via `chat.send` under the key.
- On resume turns (backend passes `resume_session_id` from prior `runtime_session_id` stored in `Conversation`):
  - `assemble_context(..., native_resume_available=True)` returns bare `current` prompt (no history wrapper).
  - We send **only** the new user message under the same `sessionKey`.
  - No re-send of system prompt or prior turns.
- The key is captured from `result.session_id` and persisted via `upsert_conversation` + posted in `post_trigger_complete`.
- Next dispatch for the scope gets it back via `get_runtime_session` because openclaw now advertises the `"resume"` capability.
- Equivalent to CLI: the sessionKey *is* the long-lived resume handle for the thread under the runner.

This eliminates the expensive full history assembly, large wire payloads, and repeated context bloat on every turn.

## Changes
- `runtimes/openclaw.py`: capabilities → `("stream_events", "resume")`, detailed comments on runner layering + native WS, `introspect` advertises `native_ws`.
- `daemon/executor.py`: new `run_openclaw_ws()` with proper v4 handshake (operator + tool-events), subscribe, `chat.send` (minimal on resume), event translation to internal text/tool events, batching to `on_event`. Uses `resume_session_id` to decide lean send.
- `daemon/core.py`: route openclaw to WS path (not http_gateway), MCP register + inflight(pid=0) + derive before WS, pass `resume_session_id`, prefer stored resume key as the long-lived sessionKey.
- `backend/forge/runtime_client.py`: `OpenClawAdapter.chat` now uses native WS (with runner target). Updated `_oc_ws_call` to protocol 4. Direct chat path benefits from WS.
- `backend/forge/services.py`: comments updated; resume cap now applies to openclaw; assemble_context short-circuit used.
- Minor: base.py, tests, docs/comments.

## Testing / verification notes
- Compiles cleanly.
- For a scope's first openclaw turn: full system injected once.
- Subsequent turns: lean prompt + same sessionKey.
- Events should now stream (board glow, run logs populate live, no "says one thing").
- session_id roundtrips so resume works across daemon restarts etc.
- Still registers MCPs per-dispatch for the runner.

## Follow-ups (out of scope here)
- Wire `sessions.abort` (or `chat.abort`) in `_cancel` for openclaw WS (currently best-effort via scope record).
- Make direct UI chat path in `send_runtime_message` also lean for openclaw resume (currently still does 20-row build in the fallback branch).
- Optional: implement `clear_handle` for openclaw if we expose session reset.
- Better timeout / reconnect for long WS turns.
- Update frontend comments about "openclaw HTTP".

## PR checklist
- [x] Capabilities/contract followed (stream_events + resume).
- [x] Long-lived sessionKey resume implemented (no full history).
- [x] Runner + "Agentira on top" pattern preserved and documented.
- [x] Ollama untouched.
- [x] Inflight / heartbeats / running state supported (pid=0 record).
- [x] Streaming events via on_event.

Closes the "running not showing + one thing and stops" for openclaw task runs, and the inefficiency of history rebuilds.
