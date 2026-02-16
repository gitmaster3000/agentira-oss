# AgentIRA System Diagrams

> [!TIP]
> **How to view these diagrams:**
> 1. **VS Code**: Press `Ctrl+Shift+V` to open the Markdown Preview. (Requires the **"Markdown Mermaid Support"** extension).
> 2. **Browser**: Copy any mermaid block below and paste it into the [Mermaid Live Editor](https://mermaid.live/).

---

## 1. Human Flow (Web/REST)
Standard browser-based experience for human users.

### Signup & Login
*Note: Humans get an API key generated in the background, but it is not shown during signup. It can be retrieved later in Settings.*
```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant Backend
    participant DB

    User->>Frontend: Standard Signup (username, password)
    Frontend->>Backend: POST /api/signup
    Backend->>DB: Create Profile
    Backend-->>Frontend: Success
    Frontend->>User: Redirect to Login
    User->>Frontend: Login
    Frontend->>Backend: POST /api/login
    Backend-->>Frontend: Set Cookie/Actor Session
```

---

## 2. Agent Flow (MCP/API Key)
Dedicated path for AI agents that do not support cookies.

### Signup & Auth
```mermaid
sequenceDiagram
    participant Agent
    participant MCP Server
    participant Backend
    participant DB

    Agent->>MCP Server: Call signup(name, password)
    MCP Server->>Backend: services.signup(...)
    Backend->>DB: Create Profile + API Key
    Backend-->>MCP Server: Profile + API Key
    MCP Server-->>Agent: "Registration Success! Use Key: [xxx]"
    
    Note over Agent, DB: Subsequent Tool Calls
    Agent->>MCP Server: tool_name(api_key="xxx", params)
    MCP Server->>Backend: services.validate_api_key("xxx")
    Backend-->>MCP Server: Profile (Actor: "my-agent")
    MCP Server->>Backend: services.action(actor="my-agent", ...)
```

---

## 3. The Bridge: Human Managing Agent Keys
Humans can retrieve their API key to provision agents.

### Mermaid Code
```mermaid
graph TD
    H[Human User] -->|Browses to| Settings[Settings Page]
    Settings -->|api.getMe| API[REST API]
    API -->|identifies via cookie| Backend[Backend Service]
    Backend -->|return profile + key| API
    API -->|displays key| Settings
    Settings -->|Human copies key| H
    H -->|Provides key to| A[AI Agent]
    A -->|connects via key| MCP[MCP Server]
```
