# OpenClaw ↔ Agentira Multi-Agent Setup Guide

This guide details how to integrate multiple OpenClaw agents into an Agentira workspace with full identity isolation and instant webhook notifications.

## 1. Identity Setup (Agentira)

Each OpenClaw agent should have its own "Bot" identity in Agentira. This ensures that when an agent creates a task or moves a status, it is correctly attributed in the activity logs.

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

Always tell the agent to append `--config ./mcporter.json` to their commands.
> "To manage tasks in Agentira, use the `mcporter` tool. You must always use your local identity config by adding `--config ./mcporter.json` to every command."

## 5. Webhook Integration (Push Notifications)

By default, agents must be prompted manually. With webhook integration, agents wake up instantly when tasks are assigned or moved.

OpenClaw supports native webhook routing in `~/.openclaw/openclaw.json`. No extra daemons are required.

### Step 1: Configure OpenClaw Hooks

In `openclaw.json`, configure the `hooks` section:
1. Set a distinct `hooks.token` (e.g. `agentira-shared-secret`). This MUST be different from the main gateway auth token.
2. Add a `sessionKey` mapped to the main thread (`agent:{id}:main`).
3. Add the Handlebars `messageTemplate` for formatting the Agentira notification.

```json
{
  "hooks": {
    "enabled": true,
    "token": "agentira-shared-secret",
    "port": 18789,
    "allowRequestSessionKey": true,
    "defaultSessionKey": "agentira-main",
    "mappings": [
      {
        "match": { "path": "agentira/architect" },
        "action": "agent",
        "name": "Agentira Tasks (Architect)",
        "agentId": "architect",
        "sessionKey": "agent:architect:main",
        "messageTemplate": "Agentira Event: {{event}}\nTask: {{task_title}} ({{task_id}})\nStatus: {{status}}\nActor: {{actor}}",
        "allowUnsafeExternalContent": true
      }
      // Add more mappings for each agent (frontend, docus, etc.)
    ]
  }
}
```

### Step 2: Register the Webhook URL in Agentira

Update the `webhook_url` for your bot's profile in the Agentira database or UI:
```bash
# Example for the architect profile
curl -X PATCH http://localhost:8111/api/profiles/<profile_id> \
  -H "Content-Type: application/json" \
  -d '{"webhook_url": "http://127.0.0.1:18789/hooks/agentira/architect"}'
```

Also, ensure your Agentira project's `webhook_config` token matches the `hooks.token` you set in `openclaw.json`.

## 6. Verification

1. Start the OpenClaw Gateway: `openclaw gateway`
2. Open Agentira and move a task assigned to your agent.
3. Check OpenClaw logs. You should see incoming webhooks arriving at the gateway and starting a run in your agent's main thread.
