# AgentIRA — Lean Task Manager for AI Agents

AgentIRA is a high-performance, lean task management system purpose-built for AI agents—**confirmed working with Antigravity and Claude**—with robust human oversight. It follows a "two-door" architecture, providing both an **MCP Server** for agentic interaction and a **REST API** for human-facing web dashboards.

> **📍 Where we're going:** see [`AGENTIRA_VISION.md`](./AGENTIRA_VISION.md) — the architectural north star. Read it before starting any feature; every implementation decision should move toward this vision. It covers the trust architecture (evidence over assertion), the universal workflow pattern (Trigger → Audit → Plan → Execute → Verify → Deliver), workflow templates, and the verified state machine.

## 🚀 Features

### Core Management
- **Projects & Scoping**: Create isolated workspaces, invite members, and enforce data visibility rules.
- **Kanban Task Board**: Full lifecycle management with drag-and-drop status transitions.
- **RBAC**: Granular permission system (Admin, Member, Viewer) guarding critical actions.
- **Attachments**: Secure file uploads and downloads linked to tasks.

### AI & Audit
- **Native MCP Support**: 15+ tool integrations exposed natively to AI agents via Stdio transport.
- **Unified Audit Log**: Every action (create, update, assign, move) is recorded in a tamper-evident activity log.
- **Notifications**: Real-time event signaling (long-polling) ensures users and agents stay in sync instantaneously.

## 🏃 Quick Start

### 1. Prerequisites
- Python 3.11+
- Node.js 18+
- The frontend lives in a **separate sibling repo**: `agentira-frontend`. Clone both repos under the same parent directory:
  ```
  flowty/
  ├── agentira/           ← this repo (backend, daemon CLI, docker-compose)
  └── agentira-frontend/  ← UI repo
  ```
  `docker-compose.yml` references the frontend via the relative path `../agentira-frontend`. If the sibling layout is not preserved, `docker compose build frontend` will fail.

### 2. Setup
```bash
# Install Backend Dependencies
pip install -e "."

# Install Frontend Dependencies
cd ../agentira-frontend
npm install
```

### 3. Run the App
Start the unified backend and the frontend dev server:
```bash
# Terminal 1: Backend REST API (http://localhost:8111)
python run.py

# Terminal 2: Frontend (http://localhost:3111)
cd frontend
npm run dev
```

## 🐳 Running via Docker Compose

Three explicit environments. **All three can run simultaneously** on one host — they use distinct ports + isolated compose project names so containers, volumes, and networks don't collide.

| Env | Frontend URL | Backend | MCP | DB | Hot reload | Project name |
|---|---|---|---|---|---|---|
| **dev** | http://localhost:3111 | :8111 | :8000 | SQLite | ✅ vite + uvicorn | `agentira` (default) |
| **qa** | http://localhost:3112 | :8112 | :8001 | Postgres | ❌ | `agentira-qa` |
| **prod** | http://localhost:3113 | (internal) | (internal) | Postgres | ❌ | `agentira-prod` |

### Bring them up

```bash
# Dev — auto-loads docker-compose.override.yml
docker compose up -d

# QA — alongside dev
docker compose -p agentira-qa \
  -f docker-compose.yml -f docker-compose.qa.yml \
  --env-file .env.qa up -d

# Prod — alongside dev + qa
docker compose -p agentira-prod \
  -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file .env.prod up -d
```

### First-time setup (qa or prod)

```bash
cp .env.qa.example .env.qa     # or .env.prod.example .env.prod
# Edit and fill in JWT_SECRET (openssl rand -hex 32) and POSTGRES_PASSWORD.
```

Both files are gitignored. Compose refuses to start qa or prod if `JWT_SECRET` or `POSTGRES_PASSWORD` is missing — better than a silent insecure default.

### What each environment differs on

- **dev**: `docker-compose.override.yml` auto-loads. Frontend runs Vite dev server (HMR), backend runs uvicorn `--reload` over volume-mounted source. JWT secret is hard-coded so logins survive `--build`. Default ports.
- **qa**: Postgres replaces SQLite; image is the truth (no source mount). Ports +1 from dev so it coexists.
- **prod**: Backend + MCP NOT exposed to host (frontend is the only public surface). `restart: unless-stopped`, healthchecks, resource limits. Hot reload disabled (`RAILWAY_ENVIRONMENT=production`). Frontend port defaults to 3113 for local-side-by-side; override via `FRONTEND_PORT` in `.env.prod` for real deploys.

### Stop / wipe

```bash
docker compose down                    # dev only
docker compose -p agentira-qa down     # qa only
docker compose -p agentira-prod down   # prod only
docker compose down -v                 # also delete volumes (DB wiped)
```

## 🤖 MCP Configuration
To connect an agent (e.g., Claude Desktop, Cursor, or Antigravity), use the following configuration.

### HTTP/SSE (Recommended)
This is the verified configuration for **Antigravity** and **Claude**.

```json
{
  "mcpServers": {
    "agentira": {
      "serverUrl": "http://127.0.0.1:8111/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY_HERE"
      }
    }
  }
}
```

> [!NOTE]
> The default port for the backend is `8111`. Ensure your `Authorization` header includes a valid Bearer token.

### Stdio (Alternative)
If you prefer to run the server as a local process:

```json
{
  "mcpServers": {
    "agentira": {
      "command": "python",
      "args": ["-m", "backend.mcp_server"],
      "cwd": "C:\\agentira",
      "env": {
        "PYTHONPATH": "C:\\agentira"
      }
    }
  }
}
```

## 🏗 Architecture
**Facade Pattern**: Both `mcp_server.py` and `rest_api.py` call into a unified `services.py` layer, ensuring business logic, permissions, and audit logging remain consistent regardless of access method.

---
Built with ❤️ for AI-Human collaboration.
