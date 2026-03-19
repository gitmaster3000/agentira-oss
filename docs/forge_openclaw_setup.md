# Forge ↔ OpenClaw Integration Setup

## Overview

Forge is the management plane for OpenClaw agents. Communication uses:
- **HTTP** for chat (`/v1/chat/completions`) and triggers (`/hooks/agent`)
- **WebSocket RPC** for live status data (sessions, costs)

## Prerequisites

1. OpenClaw running locally (default: `http://127.0.0.1:18789`)
2. Gateway token from `~/.openclaw/openclaw.json` → `gateway.auth.token`
3. Hooks token from `~/.openclaw/openclaw.json` → `hooks.token`

## Step 1: Enable Chat Completions in OpenClaw

Add to `~/.openclaw/openclaw.json` inside the `gateway` section:

```json
"http": {
  "endpoints": {
    "chatCompletions": {
      "enabled": true
    }
  }
}
```

Full gateway section example:
```json
"gateway": {
  "port": 18789,
  "mode": "local",
  "bind": "loopback",
  "auth": {
    "mode": "token",
    "token": "YOUR_GATEWAY_TOKEN"
  },
  "http": {
    "endpoints": {
      "chatCompletions": { "enabled": true }
    }
  }
}
```

**Restart OpenClaw** after editing: `openclaw restart`

## Step 2: Configure Agents in Forge

Each Forge agent needs these fields set (Config tab → Runtime Connection):

| Field | Value | Purpose |
|---|---|---|
| **Runtime Type** | `openclaw` | Selects OpenClaw integration |
| **Gateway URL** | `http://127.0.0.1:18789` | OpenClaw gateway address |
| **Agent Name** | e.g. `architect`, `frontend` | Must match agent `id` in `openclaw.json → agents.list` |
| **Gateway Token** | Your gateway auth token | Used for `/v1/chat/completions` and WebSocket RPC |
| **Hooks Token** | Your hooks auth token | Used for `/hooks/agent` fire-and-forget triggers |

### Finding Your Tokens

**Gateway Token** — in `~/.openclaw/openclaw.json`:
```json
"gateway": { "auth": { "token": "YOUR_GATEWAY_TOKEN" } }
```

**Hooks Token** — in `~/.openclaw/openclaw.json`:
```json
"hooks": { "token": "YOUR_HOOKS_TOKEN" }
```

Click the eye icon next to each token field to show/hide the value.

## Step 3: Verify

### Health Check
```bash
curl http://127.0.0.1:18789/health
# Expected: {"ok":true,"status":"live"}
```

### Chat Completions
```bash
curl -X POST http://127.0.0.1:18789/v1/chat/completions \
  -H "Authorization: Bearer YOUR_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openclaw:architect",
    "messages": [{"role": "user", "content": "Hello, who are you?"}]
  }'
```
Expected: OpenAI-compatible response with `choices[0].message.content`.

### Hook Trigger
```bash
curl -X POST http://127.0.0.1:18789/hooks/agent \
  -H "Authorization: Bearer YOUR_HOOKS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agentId": "architect",
    "message": "Test message from Forge"
  }'
```

### In the UI
1. Go to **Forge → Agents** — configured agents should show **Online** (green)
2. Open an agent → **Chat tab** → send a message → see real AI response
3. Open an agent → **Overview tab** → see live OpenClaw status + sessions
4. Open an agent → **Config tab** → verify both tokens are set (click eye to reveal)

## How Online/Offline Works

- Every time the agent list or detail page loads, Forge pings the gateway (`GET /health`)
- If the gateway responds, all agents on that URL get their heartbeat refreshed → **Online**
- If no heartbeat within 2 minutes → **Offline**
- Agents with no `runtime_url` set are always **Offline**
- Agents in **Busy** state (active run) are not overridden

## Architecture

```
Frontend (React)
    │
    ▼
Forge API (FastAPI)
    │
    ├── GET  /health                  → heartbeat / online status
    ├── POST /v1/chat/completions     → synchronous chat (Gateway Token)
    ├── POST /hooks/agent             → fire-and-forget trigger (Hooks Token)
    └── ws://host:port/?auth.token=X  → JSON-RPC for sessions/costs
    │
    ▼
OpenClaw Gateway (:18789)
    │
    ▼
AI Provider (Gemini, Claude, etc.)
```

## Troubleshooting

| Problem | Fix |
|---|---|
| All agents offline | Check OpenClaw is running: `curl http://127.0.0.1:18789/health` |
| Chat returns error | Verify `chatCompletions.enabled: true` in openclaw.json, restart OpenClaw |
| 401 on chat | Check Gateway Token matches `gateway.auth.token` in openclaw.json |
| 401 on hooks | Check Hooks Token matches `hooks.token` in openclaw.json |
| Agent not found on chat | Verify Agent Name matches an `id` in `agents.list` in openclaw.json |
