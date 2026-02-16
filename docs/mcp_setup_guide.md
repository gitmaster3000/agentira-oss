# AgentIRA MCP Setup & API Key Guide

This guide explains how to configure Agentira as a **Secure Remote MCP Server** using Server-Sent Events (SSE) and Header-based Authentication.

## 1. Prerequisites

Ensure you have the Agentira backend installed:
```bash
cd c:\agentira
pip install -e "."
# Install server dependencies
pip install mcp[cli] uvicorn starlette sse-starlette
```

## 2. Running the Server

Start the Agentira MCP server as a web service:

```bash
# This starts the SSE server on http://0.0.0.0:8000
python -m backend.mcp_server
```

You should see output indicating `Uvicorn running on http://0.0.0.0:8000`.

## 3. How to Use the API Key

Agentira provides a "One-Click" setup flow to make configuration as easy as possible.

### Step 1: Retrieve your Config from the Dashboard

1.  Open the Agentira Dashboard and go to **Settings**.
2.  Create a new bot or find an existing one.
3.  Click the **"Config"** button (or **"Copy MCP Config"** in the creation modal).

This will copy a pre-filled JSON snippet to your clipboard.

### Step 2: Configure Client (JSON)

Paste the copied snippet into your MCP settings file (e.g., `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "agentira": {
      "url": "http://localhost:8000/sse",
      "headers": {
        "Authorization": "Bearer ag_..."
      }
    }
  }
}
```

> **Security Note:** The dashboard handles the key securely. By using the "Copy Config" button, you avoid manual editing errors and keep your keys organized.
> **Security Tip:** Most MCP clients (like Claude Desktop) support environment variable interpolation. You can avoid hardcoding the key by using the `${env:VARIABLE_NAME}` syntax:
>
> ```json
> {
>   "headers": {
>     "Authorization": "Bearer ${env:AGENTIRA_API_KEY}"
>   }
> }
> ```
> **About .env files:** Most MCP clients (like Claude Desktop) do not natively load `.env` files. Instead, they prefer the `env` object inside the JSON configuration. If you are using **Cursor**, you can use the `envmcp` tool to load variables from a `.env.mcp` file.

## 4. Usage

Once connected, the agent can use tools like `list_tasks`, `create_task`, etc.
**The Agent does NOT need to pass an API key.** The server automatically identifies the user from the `Authorization` header.

## 5. Deployment (Optional)

To expose this securely to the internet:
1.  Run the server behind a reverse proxy (Nginx/Caddy) with HTTPS.
2.  Provide the HTTPS URL in the client config.
3.  The Authorization header ensures only your client can access the tools.
