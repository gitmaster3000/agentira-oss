# AgentIRA MCP Setup Guide

This guide explains how to connect various AI agents and IDEs to the AgentIRA MCP server.

### 🚀 1. Antigravity (Local Project Agents via Shim)
The Proxy Shim (`scripts/mcp_proxy.py`) is designed for **per-workspace portability**. It allows multiple projects to have their own unique API keys without ever touching your global IDE configuration.

#### API Key Discovery (The Portable Way)
The preferred method is to place your key in a text file at the root of your project:
- **Path**: `.agent/mcp_key.txt`
- **Content**: Just the raw API key.
- **Why**: This allows the shim to automatically pick up the correct key for whichever project you have open in your IDE.

#### Configuration (`mcp_config.json`)
By using the shim, your IDE configuration stays **generic** and unchanging:

```json
{
  "mcpServers": {
    "agentira-shim": {
      "command": "python",
      "args": ["scripts/mcp_proxy.py"],
      "env": {} 
    }
  }
}
```
> [!IMPORTANT]
> Leave the `env` block empty or omitted. The shim will discover the `AGENTIRA_API_KEY` by searching upwards from your current working directory for the `.agent/mcp_key.txt` file.

### Benefits
- **Zero-Config Switching**: Switch between Project A and Project B; the shim finds the right key automatically.
- **Security**: No API keys are hardcoded in your global configuration files.
- **Workspace Awareness**: Automatically sends `X-Proxy-Workspace` so tools are correctly scoped.

---

## 🛠️ 2. Cursor / VS Code (Direct SSE)
Direct connection via the standard protocol (no shim required).

### Setup in Cursor
1. Go to **Settings** -> **Cursor Settings** -> **General** -> **MCP**.
2. Click **+ Add New MCP Server**.
3. **Name**: `AgentIRA`
4. **Type**: `sse`
5. **URL**: `http://127.0.0.1:8000/sse`
6. **Headers**:
   - `Authorization`: `Bearer your_api_key_here`

---

## 🧩 3. Claude Desktop
Add to your configuration file (usually `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "agentira": {
      "command": "python",
      "args": ["-m", "backend.mcp_server"],
      "env": {
        "AGENTIRA_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

---

## 🦞 4. OpenClaw
OpenClaw doesn't natively support the `mcpServers` block in its main config. Instead, it uses the official **mcporter** skill. We recommend configuring this strictly per-agent so each agent has its own secure identity.

1. Install the `mcporter` CLI globally:
   ```bash
   npm install -g mcporter
   ```
2. Navigate to your specific agent's workspace directory (e.g., `C:\openclaw team\architect`).
3. Create a `mcporter.json` file inside that directory to define the Agentira MCP HTTP bridge:
   ```json
   {
     "mcpServers": {
       "agentira": {
         "command": "npx",
         "args": [
           "-y",
           "@nimbletools/mcp-http-bridge",
           "--endpoint",
           "http://127.0.0.1:8000/mcp",
           "--token",
           "your_agent_specific_api_key_here"
         ],
         "env": {}
       }
     }
   }
   ```
4. Update your global `~/.openclaw/openclaw.json` to tell the agent to load that specific config:
   ```json
   "list": [
     {
       "id": "architect",
       "skills": {
         "mcporter": {
           "configPath": "C:\\openclaw team\\architect\\mcporter.json"
         }
       }
     }
   ]
   ```
5. Your OpenClaw agent can now uniquely authenticate and call Agentira tools natively.

---

## ✅ Verification
Ensure your server is healthy and tests are green:
```bash
cd bruno
bru run --env local
```
All collection tests should return `✓ PASS`.
