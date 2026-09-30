# OpenWorker headless spike (P0 items 1-2)

Throwaway. Pinned: `andrewyng/openworker@c34615de` (v0.2.3, MIT). Source refs below are `coworker/server/app.py` unless noted.

## Run it

```
docker build -t openworker-spike .
docker run -d --name ow-spike -p 127.0.0.1:8765:8765 -e COWORKER_API_TOKEN=spike-token-123 openworker-spike
uv run drive.py          # needs host Ollama on :11434 (reached as host.docker.internal)
```

Result of the run committed here: `events.jsonl` (every WS frame of one turn). The agent wrote and ran `hello.py` inside the container with `ollama:qwen3.6:latest`; the driver used HTTP + WS with the token only, no Tauri shell.

## Findings

- **No Tauri needed.** `openworker-server` (console script, `coworker/server/run.py`) is a plain FastAPI/uvicorn app. `--host 0.0.0.0` is needed inside a container (default `127.0.0.1`).
- **Auth.** If env `COWORKER_API_TOKEN` is set, every HTTP call needs header `X-OpenWorker-Token: <token>` (401 otherwise). Exempt: `/v1/health` (returns bare `{"status":"ok"}` without token, full info with it), OAuth callbacks, `/v1/board/*` (own per-actor tokens). If the env var is unset the server generates a random token and writes it to `<state_dir>/sidecar-<port>.token`; always set the env var in Docker.
- **WebSocket auth is different.** No header: the token is sent as a WS *subprotocol*. Client must offer both `openworker` and the token: `subprotocols=["openworker", token]`. The server accepts with subprotocol `openworker`. Verified: token only -> client `NegotiationError` (server picks `openworker`); `openworker` only -> HTTP 403.
- **There is no "create session" REST call.** A session exists once you open `WS /ws/session/{session_id}?agent=code&workspace=<path>`; the client picks the `session_id`. The server sends `ready` when the engine is built. `GET /v1/sessions/{id}/messages` returns `{"messages": [...]}` for the persisted transcript afterwards.
- **Workspace.** `POST /v1/workspaces/temp {"session_id", "git": true}` returns `{"ok", "path", "git"}` (a temp dir under `~/OpenWorker/<session_id>`). Pass that path as `workspace=`.
- **Per-agent model.** The `model` field on the *first* `user_message` binds the session (later ones switch it). `ready.model` still shows the server default until then. Model string routes by prefix: `ollama:<name>`, bare name is OpenAI. Ollama endpoint is set over HTTP: `POST /v1/providers {"name":"ollama","fields":{"base_url":"http://host.docker.internal:11434"}}` (stored in `$COWORKER_STATE_DIR/secrets.json`, no restart). This covers P0 item 4 for Ollama.
- **Concurrency.** One turn per session; a second `user_message` mid-turn gets `input_rejected`. Inbound WS limit: 30 frames / 10 s, then the socket is closed 1008.

## WS protocol

Every frame, both directions, is JSON `{"type": str, "data": {...}}` (server -> client) or `{"type": str, ...flat fields}` (client -> server).

Client -> server:

| type | fields |
|---|---|
| `user_message` | `text`, optional `model`, `attachments[]` (`kind`: image/pdf/text), `skill` |
| `approval` | `decision`: `once`, `always_tool`, `always_command`, `always_task`, `deny` (Inbox/channels use `allow`/`always`/`deny`) |
| `question_response` / `plan_response` / `tool_response` / `directory_response` | answer to the matching `*_requested` / `plan_proposed` event |
| `interrupt`, `retry`, `set_mode`, `set_model` | control |

Server -> client (from `coworker/events.py` `EventType`, plus a few socket-level frames). Order seen in one turn:

`ready` -> `turn_start` -> `reasoning_delta`* -> `assistant_message` (with `tool_calls`) -> `tool_proposed` -> [`permission_required`] -> `tool_started` -> `tool_finished` -> `iteration_end` -> ... -> `assistant_delta`* -> `assistant_message` -> `turn_end` -> `turn_done`

Samples (from `events.jsonl`):

```
ready            {"session_id","running","agent","model","mode","workspace","temp_workspace","command_trust"}
turn_start       {"input": "<user text>"}
reasoning_delta  {"text": "The"}                               # token-level, display only
assistant_message{"text": null|str, "tool_calls": ["write_file"], "reasoning": str,
                  "usage": {"model","input","output","cache_read","cache_write"},
                  "finish_reason": "tool_calls"|"stop", "max_output_tokens": 32000}
tool_proposed    {"name": "write_file", "arguments": {...}}
tool_started     {"name": "write_file"}
tool_finished    {"name": "write_file", "status": "ok", "tool_call_id", "result_preview", "approval_origin": "bypass"}
iteration_end    {"iteration": 1}
assistant_delta  {"text": "Done"}                              # token-level final answer
turn_end         {"status": "completed", "iterations": 3}
turn_done        {}                                            # socket-level, always last; signals safe to send next message
```

Other event types exist but were not triggered: `permission_required`, `directory_requested`, `tool_requested`, `connector_requested`, `question_requested`, `plan_proposed`, `team_proposed`, `items_proposed`, `error`, `interrupted`, `compacting`/`compacted`, `continuation`, `sandbox_preparing`/`sandbox_ready`; socket-level `model_changed`, `mode_notice`, `input_rejected`.

Streaming granularity: deltas are per token (107 `reasoning_delta` + 13 `assistant_delta` frames for a short turn), so it can feed a token-streaming chat UI directly. Tool steps are three frames (`tool_proposed`/`tool_started`/`tool_finished`).

## Gaps / not covered here

- **Approvals (P0 item 3) not exercised.** `--mode auto` is an alias for `bypass-approvals` (`ready.mode` shows that), so `tool_finished.approval_origin` was `bypass` and no `permission_required` fired. The driver already answers `permission_required` with `approval`/`once`; run the server with `--mode interactive` to test it. From the source, pending prompts are also parked as Inbox items (`GET /v1/inbox`, `POST /v1/inbox/{id}/resolve`), so approvals can be answered without an open socket.
- Not done (other P0 items): OpenShell, noVNC, subscription bridge, Claude model. Only Ollama was tried, because no Anthropic key is in this environment.
- Container runs as non-root `agent`; the tool sandbox setting was left at its default. Shell tool ran directly in the container, which is the isolation boundary here.
- Server exit-with-parent and state lock are irrelevant in Docker.
