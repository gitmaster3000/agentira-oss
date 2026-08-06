# AgentIRA Integration Guide: Connecting External Agents

This guide explains how to configure any MCP-compliant agent to use the AgentIRA server.

## Overview

You can connect external agents to AgentIRA using two primary methods:
1.  **Proxy Shim (Recommended for Local Agents)**: Handles per-workspace API keys automatically.
2.  **Direct SSE (Recommended for Cloud/Custom Agents)**: Minimal setup, connects directly to the server.

---

## Method 1: Local Proxy Shim
*Best for: VS Code (Cline/Roo), Cursor, Windsurf, or CLI agents.*

The Proxy Shim (`scripts/mcp_proxy.py`) automatically discovers the correct API key for your project.

### Configuration
Update your agent's MCP config file (e.g., `mcp_config.json`):

```json
{
  "mcpServers": {
    "agentira": {
      "command": "python",
      "args": [
        "C:/agentira/scripts/mcp_proxy.py"
      ],
      "env": {
        "AGENTIRA_API_KEY": "your_global_key_if_not_using_file"
      }
    }
  }
}
```

### Key Discovery
The shim looks for keys in this order:
1.  **Environment Variable**: `AGENTIRA_API_KEY`
2.  **Workspace File**: `.agent/mcp_key.txt` (inside the folder you open)

---

## Method 2: Direct SSE Connection
*Best for: Claude Desktop, Custom Python/Node.js bots, or hosted agents.*

Connect directly to the server endpoint with a fixed token.

### Configuration
Use the `serverUrl` field in your configuration:

```json
{
  "mcpServers": {
    "agentira": {
      "serverUrl": "http://127.0.0.1:8000/sse",
      "headers": {
        "Authorization": "Bearer YOUR_AGENTIRA_API_KEY"
      }
    }
  }
}
```

---

## Verification
To test if the integration is working, ask the agent to run the following command or tool:

1.  **Identity Check**: `get_me()`
    - *Expected*: "Hello! You are connected as Client ID: [YourName]."
2.  **List Projects**: `list_projects()`
    - *Expected*: A list of your active AgentIRA projects.

---

## Troubleshooting
- **404 Errors**: Ensure the server is running on `127.0.0.1:8000` and you are using the `/sse` path.
- **Empty Tools List**: Check the server logs (`logs/mcp_server.log`) to see if the `initialize` handshake completed.
- **Auth Errors**: Verify your Bearer token matches the key in `.agent/mcp_key.txt`.
