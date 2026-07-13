# OpenClaw engine agents (technical)

**Status:** implemented on daemon 0.2.x+ / branch `fix/openclaw-engine-per-agent`  
**Audience:** platform engineers  
**Related:** [User guide](./openclaw-agents-user.md), [MCP layering](./mcp_layering.md), ADR 009

## Goal

Use OpenClaw **only as a tool engine** (read/edit/exec + host plugins).  
Agentira owns **persona, memory, prompts, board MCP, workspace provisioning, resume ids, clear/cancel**.

## Ownership

| Concern | Owner | Mechanism |
|--------|--------|-----------|
| Desk / worktree | Agentira | Daemon materializes multi-repo desk; path in `TurnRequest.workdir` |
| Personality / system prompt | Agentira | Profile `system_prompt` → chat system message |
| Long-term memory | Agentira | Memory MCP under `~/.agentira/memory/<agent>/<project>/` |
| Board tools (`finish_run`, tasks, …) | Agentira | MCP servers registered into OpenClaw gateway |
| File/exec tools | OpenClaw | `tools.profile=full` on engine agent |
| Session id storage | Agentira | `forge_conversations.runtime_session_id` |
| OpenClaw tool-thread | OpenClaw | Session under `sessionKey` |
| Clear | Agentira | Drop `runtime_session_id` + `OpenClawRuntime.clear_handle` |
| Cancel | Agentira/daemon | Abort inflight scope + best-effort OpenClaw abort |

## 1:1 engine agents

For each Agentira agent id (e.g. `f97902c47004`):

- OpenClaw agent id: **`ar-f97902c4`** (`ar-` + first 8 alnum chars)
- Created once via `openclaw agents add` (CLI — gateway-safe config path)
- Config contract (re-applied idempotently):
  - `systemPromptOverride` = `""` (no Bloopy / SOUL injection)
  - `tools.profile` = `full`
  - `agents.defaults.skipBootstrap` = `true` (do not seed SOUL into git desks)
- **Workspace** = absolute Agentira workdir when set; bound only if changed

Code: `agentira-cli/agentira_cli/runtimes/openclaw_engine.py`

## Session keys

```
agent:ar-<agent8>:<sanitized-scope>
```

Examples:

- `agent:ar-f97902c4:task:9af8cdc493c3`
- `agent:ar-f97902c4:chat:default`

OpenClaw’s `parseAgentSessionKey` requires the `agent:<id>:…` form.  
Legacy keys `agentira:<a8>:<scope>` were treated as **default agent `main`**, so tools ran in `~/.openclaw/workspace` (often only a stray `agentira-cli` tree). Those keys are **normalized** on resume.

## Turn lifecycle

1. Daemon provisions workdir (multi-repo desk when applicable).
2. `OpenClawRuntime.execute_turn`:
   - `ensure_engine_agent(agent_id, workdir=…)`
   - register Agentira MCPs (fingerprint-skip if unchanged)
   - normalize/derive `sessionKey`
   - device pair (`operator.write`)
   - `run_openclaw_ws(…, session_key=…, workdir=…)`
3. Stream tool/text events → backend `append_trigger_events`.
4. Persist `session_id` for resume.

**One task at a time per agent** (existing serialization): workspace swap is safe when the agent moves to another desk.

## Multiple agents, same repo

Each Agentira agent gets its own engine + worktree path. Concurrent implementers do not share OpenClaw workspace slots.

## Clear / cancel

| Action | Behaviour |
|--------|-----------|
| Chat clear | Backend clears `runtime_session_id`; `clear_handle` logs engine key clear |
| Run cancel | Daemon marks scope abort; OpenClaw abort RPC is best-effort follow-up |

## Legacy `agentira-runner`

The shared placeholder is **no longer used for execution**.  
`ensure_runner_agent()` remains a daemon boot no-op-ish hook (skipBootstrap + optional leftover entry). Do not document it as the execution target.

## Failure modes (historical)

| Symptom | Cause |
|---------|--------|
| Agent only sees `agentira-cli` | sessionKey not `agent:…` → routed to `main` workspace |
| Frontend task on CLI-only tree | workdir never bound to engine agent |
| Session lock / reload storms | MCP re-register every turn (mitigated by fingerprint) |

## Tests

- Unit: `agentira-cli/tests/test_openclaw_engine.py`, `test_openclaw_ws_logging.py`
- Bruno (local docker): `bruno/rest/10-openclaw-engine/`

## Config touch points

| Path | Who writes |
|------|------------|
| `~/.openclaw/openclaw.json` agents.list | `openclaw` CLI via engine ensure/bind |
| `~/.agentira/openclaw-device.json` | device pairing |
| `~/.agentira/openclaw-engines/ar-*/` | fallback empty workspace if no desk yet |
| Agentira DB conversations | resume ids |
