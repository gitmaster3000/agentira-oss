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

## 🧩 3. Claude Desktop / OpenClaw
Add to your configuration file (usually `claude_desktop_config.json` or equivalent).

```json
{
  "mcpServers": {
    "agentira": {
      "url": "http://127.0.0.1:8000/sse",
      "headers": {
        "Authorization": "Bearer your_api_key_here"
      }
    }
  }
}
```

---

## ✅ Verification
Ensure your server is healthy and tests are green:
```bash
cd bruno
bru run --env local
```
All collection tests should return `✓ PASS`.
