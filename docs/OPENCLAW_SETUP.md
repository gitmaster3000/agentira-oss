# OpenClaw ↔ Agentira Multi-Agent Setup Guide

This guide details how to integrate multiple OpenClaw agents into an Agentira workspace with full identity isolation.

## 1. Identity Setup (Agentira)

Each OpenClaw agent should have its own "Bot" identity in Agentira. This ensures that when an agent creates a task or moves a status, it is correctly attributed in the activity logs.

### Create Service Accounts via Dashboard
1. Open the **Agentira Dashboard** in your browser.
2. Navigate to **Settings** > **Bot Management**.
3. Create a new bot for each agent (e.g., `architect`, `frontend`, `docus`).
4. **Copy the API Key** generated for each bot immediately; you will need it for the agent's local configuration.

## 2. Global OpenClaw Configuration

Ensure the `mcporter` skill is enabled in your global `~/.openclaw/openclaw.json`.

```json
{
  "skills": {
    "entries": {
      "mcporter": {
        "enabled": true
      }
    }
  }
}
```

## 3. Per-Agent Workspace Configuration

OpenClaw supports per-workspace `mcporter.json` files. This allows each agent to use its own API key without needing complex environment variable management.

### The `mcporter.json` file
In each agent's active workspace (e.g., `C:\openclaw team\architect`), create a `mcporter.json` file:

```json
{
    "mcpServers": {
        "agentira": {
            "url": "http://127.0.0.1:8000/mcp",
            "headers": {
                "Authorization": "Bearer YOUR_AGENT_SPECIFIC_API_KEY"
            }
        }
    }
}
```

## 4. Teaching Agents to use the Skill

Update your `mcporter` skill instructions (`~/.openclaw/skills/mcporter/SKILL.md`) so agents know how to load their specific identity.

**Crucial Instruction:** Always tell the agent to append `--config ./mcporter.json` to their commands.

### Example Prompt/Instruction:
> "To manage tasks in Agentira, use the `mcporter` tool. You must always use your local identity config by adding `--config ./mcporter.json` to every command."

## 5. Verification

To verify an agent has the correct identity, ask it to check its own profile:

```bash
openclaw agent --agent architect --message "Who am I in Agentira? Use mcporter get_me with --config ./mcporter.json"
```

The response should confirm the name of the specific service account you created in Step 1.

## 6. Webhook Integration (Push Notifications)

By default, OpenClaw agents discover tasks via manual prompts or scheduled runs.
With the **webhook receiver plugin**, agents react to Agentira events **instantly** —
no polling or manual trigger needed.

### Option A: Native OpenClaw Plugin (Pattern A2 — recommended)

Install the `openclaw-webhook-receiver` plugin to receive webhooks directly
inside OpenClaw. No Python daemon required.

**Install the plugin:**

```bash
# From the agentira repo root
cd openclaw-webhook-receiver
npm install

# Tell OpenClaw about the plugin (in your agent's workspace settings)
```

**Configure the plugin** in your OpenClaw agent config:

```json
{
  "plugins": {
    "openclaw-webhook-receiver": {
      "enabled": true,
      "port": 9112,
      "token": "",
      "gatewayUrl": "http://127.0.0.1:18789/v1/chat/completions",
      "gatewayToken": "",
      "agentName": "architect"
    }
  }
}
```

| Setting | Description |
|---|---|
| `port` | Webhook listener port (default: 9112). Each agent needs a unique port. |
| `token` | Shared secret for `X-Agentira-Token` validation. Empty = no auth (localhost-safe). |
| `gatewayUrl` | OpenClaw gateway completions endpoint. |
| `gatewayToken` | Bearer token for the gateway (if auth is enabled). Supports `${VAR}` interpolation. |
| `agentName` | Agent/model name passed to the gateway. |

**Register the webhook URL** with Agentira so the backend knows where to POST:

```bash
curl -X PATCH http://localhost:8111/api/profiles/<profile_id> \
  -H "Content-Type: application/json" \
  -d '{"webhook_url": "http://127.0.0.1:9112/webhook"}'
```

**Verify** — start the agent and check the plugin started:
```
[agentira-webhook] Listening on :9112 — no auth (localhost-safe)
```

Then move a task assigned to this agent. You should see:
```
[agentira-webhook] Received: event=task.moved task=abc123
[agentira-webhook] Agent triggered (HTTP 200)
```

### Option B: Python Daemon Wrapper (Pattern A1)

Use the Agentira daemon with `executor: http` to bridge webhooks to OpenClaw's
completions API. See [setup-agent-guide.md](./setup-agent-guide.md) Section 11.

```bash
# .env
AGENTIRA_DAEMON_EXECUTOR=http
AGENTIRA_DAEMON_EXECUTOR_URL=http://127.0.0.1:18789/v1/chat/completions
AGENTIRA_DAEMON_NOTIFICATION_MODE=hybrid
AGENTIRA_DAEMON_WEBHOOK_PORT=9111

python -m agents.daemon --bot-name architect --api-key <key>
```

The daemon auto-registers its webhook URL on startup — no manual curl needed.

### Multi-Agent Webhook Ports

When running multiple OpenClaw agents, each needs its own webhook port:

| Agent | Plugin Port | Daemon Port (if using A1) |
|---|---|---|
| architect | 9112 | 9111 |
| frontend | 9113 | 9121 |
| qa | 9114 | 9131 |

## Troubleshooting

- **Connection Refused**: Ensure the Agentira backend is running (`python -m backend.mcp_server`).
- **Missing Session ID**: If you see "Missing session ID" errors, ensure Agentira's `StreamableHTTPSessionManager` is NOT in `stateless=True` mode (default is False/Stateful).
- **Tool Discovery**: Run `mcporter list agentira --config ./mcporter.json` to manually verify that the CLI can see the Agentira schema.
- **Webhook not triggering**: Check that the bot profile has `webhook_url` set and the project's `webhook_config` is enabled. Start with `DEBUG` logging to see delivery attempts.
- **Agent trigger fails**: Verify the `gatewayUrl` is correct and the OpenClaw gateway is running. Check `GET http://127.0.0.1:9112/health` for plugin status.
