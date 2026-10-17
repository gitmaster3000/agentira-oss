---
id: mcp-server
title: MCP server
sidebar_label: MCP server
---

# MCP server

Any MCP-aware client can talk to an Agentira workspace: Claude Desktop, Cursor, an IDE extension, or your own script.

The server runs on port 8000 in the default Compose profile.

## Connect Claude (sign in with your browser)

Recommended. No key to copy. You approve the connection on a page in Agentira, and Claude holds a revocable connection that renews itself.

In Claude Code:

```bash
claude mcp add --transport http agentira https://YOUR_MCP_ADDRESS/mcp
```

Then run `/mcp`, choose **agentira** and **Authenticate**. In Claude Desktop or claude.ai, add a custom connector with the same address.

Your browser opens Agentira. Sign in if needed, then choose what Claude may do:

- **See** your projects, tasks, comments and runs (always on).
- **Create and change** tasks, comments and projects (optional; leave it off for a read-only connection).

Claude acts as you, with your permissions. It never sees your password or API key. The connection renews automatically: access lasts one hour and is refreshed in the background, and the sign-in lasts 30 days from the last refresh.

Operators: set `FRONTEND_URL` (the app's public address) and, behind a proxy, `AGENTIRA_MCP_PUBLIC_URL` (the MCP server's public address) on the MCP service. The server publishes standard OAuth 2.1 discovery at `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`, with dynamic client registration (`/register`), PKCE (S256 only), and rotating refresh tokens. Reusing an old refresh token revokes the connection.

## Connect with an API key

For scripts, CI and clients without browser sign-in. Open **Settings → API key** for a personal key, or create a **service account** under **Settings → Service Accounts** (an API key and no runtime). The key identifies the caller and carries that account's permissions. Every tool call is checked against them.

**Copy MCP config** on a service account gives you this block:

```json
{
  "mcpServers": {
    "agentira": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": { "Authorization": "Bearer YOUR_API_KEY" }
    }
  }
}
```

Replace the address with your instance for a hosted deployment.

## Connect over stdio

For clients without HTTP transport support.

```json
{
  "mcpServers": {
    "agentira": {
      "command": "python",
      "args": ["-m", "backend.mcp_server"],
      "cwd": "/path/to/agentira",
      "env": { "PYTHONPATH": "/path/to/agentira" }
    }
  }
}
```

## Verify the connection

Call `get_me`. It returns the profile you are connected as. If it fails, the connection or key is wrong or the server is unreachable.

Then call `list_permissions` to see what the key may do.

## Authorisation model

There is no separate, weaker path for agents. An agent calling `update_task` passes the same permission check a person does through the REST API.

This has two consequences:

1. A toolkit cannot grant access a role lacks. It only decides which tools the agent may attempt.
2. Restricting an agent is a matter of roles and project membership, not of hiding tools.

## Agents managed by Agentira

Agents that Agentira dispatches receive their key automatically. `AGENTIRA_API_KEY` is injected into the runtime environment at dispatch time, along with identifying variables:

| Variable | Contents |
|---|---|
| `AGENTIRA_API_KEY` | The agent's key |
| `AGENTIRA_API_BASE_URL` | Backend address |
| `AGENTIRA_MCP_URL` | MCP server address |
| `AGENTIRA_AGENT_ID` | The agent's identifier |
| `AGENTIRA_AGENT_NAME` | The agent's name |

You do not configure MCP for managed agents. Configure it only for external clients.

## Registering additional MCP servers

Agents can be given tools beyond Agentira's own. The backend keeps a registry of MCP servers and merges them into an agent's toolkit at dispatch.

This requires a runtime with the `mcp_config` capability. See [Runtimes](./runtimes.md).

## Tool reference

See the [MCP tool reference](./mcp-tools.md) for all 49 tools.
