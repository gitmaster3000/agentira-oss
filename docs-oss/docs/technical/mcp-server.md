---
id: mcp-server
title: MCP server
sidebar_label: MCP server
---

# MCP server

Any MCP-aware client can talk to an Agentira workspace: Claude Desktop, Cursor, an IDE extension, or your own script.

The server runs on port 8000 in the default Compose profile.

## Get an API key

Open **Settings → API key** for a personal key.

For a script or an external tool, create a **service account** instead, under **Settings → Service Accounts**. Service accounts have an API key and no runtime.

The key identifies the caller and carries that account's permissions. Every tool call is checked against them.

## Connect over HTTP

Recommended.

```json
{
  "mcpServers": {
    "agentira": {
      "serverUrl": "http://127.0.0.1:8000/mcp",
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

Call `get_me`. It returns the profile the key belongs to. If it fails, the key is wrong or the server is unreachable.

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
