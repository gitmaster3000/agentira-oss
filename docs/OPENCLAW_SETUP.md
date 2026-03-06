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

## Troubleshooting

- **Connection Refused**: Ensure the Agentira backend is running (`python -m backend.mcp_server`).
- **Missing Session ID**: If you see "Missing session ID" errors, ensure Agentira's `StreamableHTTPSessionManager` is NOT in `stateless=True` mode (default is False/Stateful).
- **Tool Discovery**: Run `mcporter list agentira --config ./mcporter.json` to manually verify that the CLI can see the Agentira schema.
