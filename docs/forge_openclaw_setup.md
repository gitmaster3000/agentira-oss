# Forge ↔ OpenClaw setup (operators)

> **Product model:** OpenClaw is a **tool engine**. Agentira owns persona, memory, MCP board tools, and the task desk.  
> Full design: [openclaw-engine-agents.md](./openclaw-engine-agents.md) · User guide: [openclaw-agents-user.md](./openclaw-agents-user.md)

## Prerequisites

1. OpenClaw gateway local (default `http://127.0.0.1:18789`)
2. Agentira daemon on the same machine
3. Device pairing for execution auth:

```bash
agentira daemon pair
openclaw devices list --json   # displayName agentira-daemon → operator.write
agentira daemon restart
```

Identity file: `~/.agentira/openclaw-device.json` (mode 0600).  
Do **not** paste the shared gateway token into Agentira for WS turns.

## What the daemon does

On each OpenClaw turn:

1. Ensures engine agent **`ar-<first8 of agent id>`** exists (`tools.profile=full`, empty system override).
2. Binds engine **workspace** to the Agentira workdir when the desk path changes.
3. Registers Agentira MCP servers (fingerprint-skip if unchanged).
4. `chat.send` with `sessionKey = agent:ar-<id>:<scope>`.
5. Streams text + tool events to the backend.

## Forge agent fields

| Field | Value |
|-------|--------|
| Runtime type | `openclaw` |
| Gateway URL | usually auto from daemon introspect |
| Model | OpenClaw-reachable model id |
| System prompt | Agentira persona (not OpenClaw SOUL.md) |

There is **no** “must match agents.list id in openclaw.json for persona” step.  
Engine agents are created automatically; do not point product agents at personal `main`.

## Legacy (removed from execution)

| Old idea | Status |
|----------|--------|
| Shared `agentira-runner` for all chats | Not used for execution |
| HTTP `/v1/chat/completions` for OpenClaw product turns | Native WS only |
| `sessionKey` like `agentira:…` without `agent:` prefix | Normalized to `agent:ar-…` |
| “Agent Name” = OpenClaw personal agent id | Dropped; Agentira display name is independent |

## Ops checks

```bash
openclaw agents list --json | jq '.[] | {id, workspace}'
# Expect ar-<id> entries with workspace under ~/.agentira/agents/.../task-* when active

agentira daemon status
```

## Related

- [MCP layering](./mcp_layering.md)
- [Daemon runbook](./daemon_runbook.md)
