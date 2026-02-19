# Technical Handover: AgentIRA MCP - Stable Baseline Reverted

### 🎯 Current State
We have **reverted** the codebase to the last known stable state (commit `1672cc4`). The "Global Proxy Package" approach was abandoned due to key discovery failures and session routing issues.

### 🏗️ Working Architecture (Baseline)
1.  **Server (`backend/mcp_server.py`)**: 
    - Using the **Unified SSE Handler** which routes both legacy IDE clients and standard SSE clients through a single session manager.
    - Resolves the "Split-Brain" issue by mounting `mcp.sse_app()` correctly.
2.  **Proxy Shim (`scripts/mcp_proxy.py`)**:
    - **Manual Script**: Must be executed directly (e.g., `python scripts/mcp_proxy.py`).
    - **Key Discovery**: Searches the current working directory for `.agent/mcp_key.txt`.
3.  **Config**: `mcp_config.json` is set to use `python scripts/mcp_proxy.py`.

### 🐞 The Remaining Challenge
- **Portability**: The user wants a way for *anyone* to use the shim easily without manually copying the `mcp_proxy.py` file into every new project.
- **The Catch**: The previous attempt to make it a global `pip` package failed because the IDE (Antigravity) starts the process with a CWD pointing to its own program folder, causing the shim to lose its search context for the local `.agent/mcp_key.txt`.

### 📋 Goal for Claude
Find a way to make the shim **globally accessible** (e.g., via a global path or package) while ensuring it **reliably discovers the workspace root** of the project currently open in the IDE, so it can find the local API key.

### 📂 Key Files
- `backend/mcp_server.py`: The protocol-compliant server.
- `scripts/mcp_proxy.py`: The working (but local) shim.
- `docs/AGENT_SETUP.md`: Current setup guide.
