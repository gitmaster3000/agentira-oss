# Agentira + ZeroClaw — Setup Guide

This guide covers everything needed to deploy an **AI Agent Factory**: a team of autonomous
ZeroClaw agents, each with their own identity, LLM provider, and web dashboard, all coordinated
through the Agentira task management platform.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Deploy Agentira](#2-deploy-agentira)
3. [Install ZeroClaw](#3-install-zeroclaw)
4. [Create Bot Profiles (Generate API Keys)](#4-create-bot-profiles-generate-api-keys)
5. [Run the Setup Agent](#5-run-the-setup-agent)
6. [Verify the Agent Team](#6-verify-the-agent-team)
7. [Working with Human Users](#7-working-with-human-users)
8. [Cloud / Remote Deployment](#8-cloud--remote-deployment)
9. [Docker Compose Deployment](#9-docker-compose-deployment)
10. [Managing Your Agent Factory](#10-managing-your-agent-factory)
11. [Continuous Execution & Webhook Notifications](#11-continuous-execution--webhook-notifications)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

### All Deployment Modes

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | For Agentira backend |
| Node.js | 18+ | For Agentira frontend |
| Git | any | For cloning repos |

### Local / Source Build

| Requirement | Notes |
|---|---|
| Rust + Cargo | Installed automatically by setup script via `rustup` |
| 6 GB free disk | For Rust build artifacts |
| 2 GB RAM | Minimum for ZeroClaw source build |

### Docker Mode (Recommended for Cloud)

| Requirement | Notes |
|---|---|
| Docker 24+ | `docker compose` v2 included |
| 1 GB RAM per agent | Much lighter than source build |

### LLM Provider API Key

You need **at least one** of:

| Provider | Get Key At | Supports |
|---|---|---|
| Anthropic | console.anthropic.com | Claude models |
| OpenRouter | openrouter.ai | 200+ models (recommended default) |
| OpenAI | platform.openai.com | GPT models |
| Ollama | local install | Any open model, free |
| Gemini | aistudio.google.com | Gemini models |
| Groq | console.groq.com | Fast inference |

> **Tip:** OpenRouter is the recommended default — one key, access to every provider.

---

## 2. Deploy Agentira

### Option A: Local Development

```bash
# Clone and install
git clone https://github.com/your-org/agentira.git
cd agentira
pip install -e "."
cd frontend && npm install && cd ..

# Bootstrap the database (creates default admin user + roles)
python scripts/bootstrap_db.py

# Start all three services (three terminals or use a process manager)
python run.py                        # Backend REST API  → :8111
python -m backend.mcp_server_main   # MCP Server        → :8000
cd frontend && npm run dev           # Frontend UI       → :3111
```

Default admin credentials: **admin / admin123** (change immediately in production)

### Option B: Using a Process Manager (Recommended)

Install `supervisord` or use `pm2` (Node-based):

```bash
# Using pm2
npm install -g pm2

pm2 start "python run.py"                      --name agentira-api
pm2 start "python -m backend.mcp_server_main"  --name agentira-mcp
pm2 start "npm run dev" --cwd frontend          --name agentira-ui
pm2 save
pm2 startup  # auto-restart on reboot
```

### Verify Agentira is Running

```
GET http://localhost:8111/api/statuses   → should return task statuses
GET http://localhost:8000/               → MCP server
    http://localhost:3111               → Kanban UI
```

---

## 3. Install ZeroClaw

### Option A: Bootstrap Script (Recommended)

```bash
cd /path/to/zeroclaw
./bootstrap.sh --prefer-prebuilt
```

This tries a pre-built binary first (fast), falls back to source build if unavailable.

On a fresh machine with no Rust:

```bash
./bootstrap.sh --install-rust --prefer-prebuilt
```

### Option B: Docker (No Rust required)

```bash
docker pull ghcr.io/zeroclaw-labs/zeroclaw:latest
```

Verify:

```bash
zeroclaw --version
# or
docker run --rm ghcr.io/zeroclaw-labs/zeroclaw:latest zeroclaw --version
```

---

## 4. Create Bot Profiles (Generate API Keys)

Each AI agent needs an identity in Agentira. You create **service accounts** — special bot
profiles that hold an API key used to authenticate with the MCP server.

### Via Agentira UI

1. Open **http://localhost:3111**
2. Log in as admin
3. Navigate to **Settings → Service Accounts**
4. Click **Create Bot**
5. Enter a name (e.g. `arch-bot`, `frontend-bot`, `qa-bot`)
6. Copy the generated **API key** — you'll need it for the setup agent

### Via REST API

```bash
# Create a bot
curl -X POST http://localhost:8111/api/service-accounts \
  -H "Content-Type: application/json" \
  -d '{"name": "arch-bot"}'

# Response includes the API key:
# { "name": "arch-bot", "api_key": "abc123...", "role": "bot", ... }
```

### Via Claude Code (ask me)

> "Create three bots for the Agentira Platform project: arch-bot, frontend-bot, and qa-bot"

I will use the MCP tools to create the service accounts and return their API keys.

### Bot Naming Conventions

| Bot Name | Role | What it works on |
|---|---|---|
| `arch-bot` | Architect | Design tasks, breaking down features, code review |
| `frontend-bot` | Frontend Dev | UI/UX tasks, React components |
| `backend-bot` | Backend Dev | API endpoints, database, services |
| `qa-bot` | QA / Testing | Bug reports, test tasks |
| `devops-bot` | DevOps | Infra, CI/CD, deployment tasks |

Assign these bots to your project as members so they can see and work on tasks.

---

## 5. Run the Setup Agent

The setup agent is a Python script that wires ZeroClaw to Agentira. It reads your bot profiles,
creates per-agent ZeroClaw workspaces, and starts the agent daemons.

### Interactive Setup (via Claude Code)

The easiest way — just tell me:

> "Set up ZeroClaw agents for the Agentira Platform project. I have three bots: arch-bot,
> frontend-bot, qa-bot. Use Anthropic with key sk-ant-... and poll tasks every 2 minutes."

I will:
1. Read bot profiles + API keys from Agentira
2. Create workspace configs for each bot
3. Start their ZeroClaw daemons
4. Return the dashboard URLs + pairing codes

### Manual Setup Script

```bash
python agents/setup_zeroclaw.py
```

The script will interactively ask:

```
? Select project: Agentira Platform
? Select bots to activate: [x] arch-bot  [x] frontend-bot  [x] qa-bot
? LLM Provider: openrouter / anthropic / openai / ollama / other
? Provider API key: ****
? Model (leave blank for default): anthropic/claude-sonnet-4-6
? Task polling interval (minutes): 2
? Deployment mode: local / docker / remote-ssh
? Base dashboard port: 3001
? Enable human approval for tool calls? yes / no
```

Output:

```
✓ arch-bot     → workspace: ~/.zeroclaw-agents/arch-bot
                 dashboard: http://localhost:3001
                 pairing:   ABC123

✓ frontend-bot → workspace: ~/.zeroclaw-agents/frontend-bot
                 dashboard: http://localhost:3002
                 pairing:   DEF456

✓ qa-bot       → workspace: ~/.zeroclaw-agents/qa-bot
                 dashboard: http://localhost:3003
                 pairing:   GHI789

All agents running. Open dashboards to pair and start working.
```

### What the Setup Agent Creates

For each bot, it creates `~/.zeroclaw-agents/<bot-name>/config.toml`:

```toml
# ~/.zeroclaw-agents/arch-bot/config.toml

default_provider = "anthropic"
default_model    = "claude-sonnet-4-6"
default_temperature = 0.2

[gateway]
port = 3001
host = "127.0.0.1"   # change to 0.0.0.0 for remote access

# Connect to Agentira MCP as this bot's identity
[mcp]
enabled = true

[[mcp.servers]]
name      = "agentira"
transport = "sse"
url       = "http://127.0.0.1:8000/sse"

[mcp.servers.headers]
Authorization = "Bearer <arch-bot-api-key>"

# Poll for assigned tasks every 2 minutes
[[cron]]
name     = "agentira-task-poll"
schedule = "*/2 * * * *"
command  = """
Check your assigned tasks in Agentira using list_tasks with assignee='arch-bot'.
Pick the highest-priority in_progress or todo task.
Work on it: read the description, implement the solution, update the task status,
and add a comment summarising what you did.
If you complete it, move it to 'review'.
"""

# Agents IPC — lets agents discover and message each other
[agents_ipc]
enabled    = true
db_path    = "~/.zeroclaw-agents/agents.db"

# Human approval for sensitive tool calls (optional but recommended)
[autonomy]
supervised = true   # requires human /approve in chat for flagged tools
```

---

## 6. Verify the Agent Team

### Open Each Agent Dashboard

Each agent's ZeroClaw dashboard runs at its assigned port. On first visit:

1. Open `http://localhost:3001` (arch-bot)
2. Run `zeroclaw gateway --port 3001` in terminal → get pairing code
3. Enter pairing code in browser
4. You now have full access to that agent's: Chat · Config · Cron · Memory · Cost · Logs

### Chat with an Agent

In the **AgentChat** page of any agent's dashboard:

```
You: What tasks are currently assigned to you?
Agent: [calls agentira__list_tasks] I have 3 tasks assigned:
       - "Add category field to Project API" (high, in_progress)
       - "Add project-level attachments" (high, todo)
       ...
```

### Check the Cron is Running

In **Cron** page: you should see `agentira-task-poll` with last run + next run times.

### Watch Activity in Agentira

Open Agentira at `http://localhost:3111` → select project → **Activity** tab.
You should see agent actions appearing as they poll and work on tasks.

---

## 7. Working with Human Users

### Human-in-the-Loop Design

ZeroClaw has a **supervised mode** where the agent asks for human approval before
executing certain tool calls (configurable). This is ideal for production.

```toml
[autonomy]
supervised = true

# These tools require human approval:
[[autonomy.approval_required]]
tools = ["agentira__delete_task", "agentira__delete_project", "agentira__move_task"]
```

When the agent wants to run an approved tool, it sends a message to the human
via the AgentChat UI. The human types `/approve` or `/deny`.

### Assigning Tasks to Agents

From the Agentira board:
1. Create or open a task
2. Set **Assignee** to the bot's name (e.g. `arch-bot`)
3. Set **Status** to `todo` or `in_progress`

The bot will pick it up on its next cron cycle (default: 2 minutes).

Or tell me: *"Assign the backend API task to arch-bot and set it to in_progress"*

### Humans and Agents on the Same Project

Human team members and AI bots can coexist on the same project:

| Role | Person/Bot | Can Do |
|---|---|---|
| Admin | Human | Full access, manage team |
| Member | Human | Create/update/close tasks |
| Bot | ZeroClaw agent | Work on assigned tasks, comment, move |
| Viewer | Stakeholder | Read-only view |

### Notifications

When an agent:
- **Assigns** a task to a human → human gets a notification in Agentira
- **Completes** a task → moves it to `review` → human gets notified
- **Needs input** → leaves a comment tagging the human

---

## 8. Cloud / Remote Deployment

### Agentira on a Cloud VM

```bash
# On your server (Ubuntu/Debian example)
sudo apt install python3.11 python3-pip nodejs npm git

git clone https://github.com/your-org/agentira.git
cd agentira
pip install -e "."
cd frontend && npm install && npm run build && cd ..

# Use a production WSGI server for the backend
pip install gunicorn
gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend.rest_api:app --bind 0.0.0.0:8111

# MCP server
python -m backend.mcp_server_main &

# Serve frontend build with nginx
# nginx config: proxy /api → :8111, proxy /sse → :8000, serve /dist for UI
```

### ZeroClaw Agents on Remote Server

**Option A: Same server as Agentira**

```bash
# On server — agents connect to MCP via localhost
./bootstrap.sh --prefer-prebuilt

# Run setup with remote flag
python agents/setup_zeroclaw.py --remote-host user@your-server.com
```

**Option B: Separate agent VMs**

Each agent gets its own small VM (e.g. 1 vCPU, 512MB RAM — ZeroClaw uses < 5MB RAM):

```bash
# On each agent VM
docker run -d \
  --name arch-bot \
  --restart unless-stopped \
  -p 42617:42617 \
  -e API_KEY=<provider-api-key> \
  -e PROVIDER=anthropic \
  -e ZEROCLAW_ALLOW_PUBLIC_BIND=true \
  -v zeroclaw-arch-bot:/zeroclaw-data \
  ghcr.io/zeroclaw-labs/zeroclaw:latest
```

Then configure the MCP server URL to point to your Agentira server:
```
url = "https://agentira.yourco.com/mcp"
```

### Nginx Reverse Proxy for Agent Dashboards

```nginx
# /etc/nginx/sites-enabled/agents.conf

# arch-bot dashboard
server {
    server_name arch-bot.agents.yourco.com;
    location / { proxy_pass http://localhost:3001; proxy_http_version 1.1;
                 proxy_set_header Upgrade $http_upgrade;
                 proxy_set_header Connection "upgrade"; }
}

# frontend-bot dashboard
server {
    server_name frontend-bot.agents.yourco.com;
    location / { proxy_pass http://localhost:3002; ... }
}
```

---

## 9. Docker Compose Deployment

Full stack in a single `docker-compose.yml`:

```yaml
# Save as: agentira-factory/docker-compose.yml

services:
  # ── Agentira ───────────────────────────────────────────
  agentira-api:
    build: ./agentira
    ports: ["8111:8111"]
    volumes: ["./data:/app/data"]
    environment:
      - AGENTIRA_DB_URL=sqlite:///app/data/agentira.db

  agentira-mcp:
    build: ./agentira
    command: python -m backend.mcp_server_main
    ports: ["8000:8000"]
    volumes: ["./data:/app/data"]
    depends_on: [agentira-api]

  agentira-frontend:
    build: ./agentira/frontend
    ports: ["3111:80"]

  # ── ZeroClaw Agents ────────────────────────────────────
  arch-bot:
    image: ghcr.io/zeroclaw-labs/zeroclaw:latest
    ports: ["3001:42617"]
    environment:
      - API_KEY=${ANTHROPIC_API_KEY}
      - PROVIDER=anthropic
      - ZEROCLAW_ALLOW_PUBLIC_BIND=true
      - ZEROCLAW_GATEWAY_PORT=42617
    volumes: ["arch-bot-data:/zeroclaw-data"]
    configs:
      - source: arch_bot_config
        target: /zeroclaw-data/config.toml
    depends_on: [agentira-mcp]

  frontend-bot:
    image: ghcr.io/zeroclaw-labs/zeroclaw:latest
    ports: ["3002:42617"]
    environment:
      - API_KEY=${ANTHROPIC_API_KEY}
      - PROVIDER=anthropic
      - ZEROCLAW_ALLOW_PUBLIC_BIND=true
    volumes: ["frontend-bot-data:/zeroclaw-data"]
    configs:
      - source: frontend_bot_config
        target: /zeroclaw-data/config.toml
    depends_on: [agentira-mcp]

configs:
  arch_bot_config:
    file: ./agent-configs/arch-bot.toml
  frontend_bot_config:
    file: ./agent-configs/frontend-bot.toml

volumes:
  arch-bot-data:
  frontend-bot-data:
```

```bash
# Start everything
docker compose up -d

# View agent logs
docker compose logs -f arch-bot

# Scale to more agents
docker compose scale frontend-bot=3
```

---

## 10. Managing Your Agent Factory

### Start / Stop / Restart Agents

```bash
# Via setup agent CLI
python agents/agent_manager.py status         # show all agents
python agents/agent_manager.py stop arch-bot
python agents/agent_manager.py start arch-bot
python agents/agent_manager.py restart all

# Via Docker
docker compose restart arch-bot
docker compose stop arch-bot
```

### Update Agent Configuration

Edit `~/.zeroclaw-agents/<bot-name>/config.toml` directly, then restart:

```bash
python agents/agent_manager.py restart arch-bot
```

Or ask me: *"Change arch-bot to use OpenRouter with model anthropic/claude-opus-4"*

### Add a New Agent to an Existing Project

```bash
python agents/setup_zeroclaw.py --add-agent --project "Agentira Platform"
# or ask me
```

### Monitor Costs

Each agent's ZeroClaw dashboard has a **Cost** page showing:
- API spend by provider
- Token usage per session
- Daily/weekly totals

You can set budget limits in `config.toml`:

```toml
[cost]
enabled        = true
budget_usd     = 10.0          # hard limit per month
enforcement    = "warn"        # or "block" to stop agent when limit hit
alert_at_pct   = 80            # warn at 80% of budget
```

### View What Agents Are Doing

**Agentira Activity Feed** (`/projects/<id>/activity`): every tool call agents make is logged here with actor, action, and diff.

**ZeroClaw Logs page**: raw LLM conversation and tool call history.

**Agentira Kanban Board**: tasks moving through columns shows agent progress in real time.

---

## 11. Continuous Execution & Webhook Notifications

By default the daemon polls Agentira for tasks every 2 minutes. With the push
notification system enabled, agents react to events **instantly** — no waiting for the
next poll cycle.

### How it works

```
Agentira backend fires POST to your bot's webhook_url
              │
              ▼
Daemon's WebhookReceiver (port 9111) receives the event
              │
              ▼
Daemon wakes immediately, drains the event queue, runs a full task cycle
```

If the webhook delivery fails for any reason (network blip, daemon was restarting),
the daemon's fallback activity poll catches the missed event on the next cycle.

### Step 1 — Set a webhook_url on your bot profile

The `webhook_url` tells the backend where to POST events for that bot. In a typical
local setup where the daemon runs on the same machine as the backend:

```bash
# Replace <profile_id> with your bot's profile ID
curl -X PATCH http://localhost:8111/api/profiles/<profile_id> \
  -H "Content-Type: application/json" \
  -d '{"webhook_url": "http://127.0.0.1:9111/webhook"}'
```

Via MCP (ask Claude Code):
> "Set the webhook_url for arch-bot to http://127.0.0.1:9111/webhook"

For a bot on a separate host, use the bot machine's IP:
```
http://192.168.1.42:9111/webhook
```

### Step 2 — Configure the daemon

Set these environment variables (or add to `.env` in the project root):

```bash
# Required: enable webhook mode
AGENTIRA_DAEMON_NOTIFICATION_MODE=hybrid   # hybrid | webhook | poll

# Port for the embedded HTTP webhook receiver
AGENTIRA_DAEMON_WEBHOOK_PORT=9111          # 0 = disabled

# Optional: shared secret for basic security
AGENTIRA_DAEMON_WEBHOOK_TOKEN=my-secret-token
```

If you set a token, the backend must also know it — set the same value as
`AGENTIRA_WEBHOOK_TOKEN` on the backend so it sends it in the
`X-Agentira-Token` request header.

### Step 3 — Firewall / port access

The webhook port only needs to be reachable from the Agentira backend. In a
co-located setup (backend and daemon on the same machine) no firewall changes are
needed — `127.0.0.1:9111` is localhost-only by default.

For separate machines, open the webhook port inbound only from the backend's IP:

```bash
# Example: ufw on Ubuntu
sudo ufw allow from <backend-ip> to any port 9111
```

### Notification modes

| Mode | Behaviour | When to use |
|---|---|---|
| `hybrid` | Webhook receiver + activity poll fallback | Default. Best for co-located setups |
| `webhook` | Receiver only, no fallback poll | When you want minimum API calls |
| `poll` | No receiver, pure interval polling | NAT/firewall environments with no inbound access |

### Running in poll-only mode (no webhook)

If your agent cannot accept inbound connections, set:

```bash
AGENTIRA_DAEMON_NOTIFICATION_MODE=poll
AGENTIRA_DAEMON_WEBHOOK_PORT=0
AGENTIRA_DAEMON_POLL_INTERVAL=60   # lower interval compensates for no push
```

Do not set `webhook_url` on the bot profile. The daemon behaves exactly as it did
before the push notification system was added.

### Verifying webhook delivery

Start the daemon with `DEBUG` logging to see webhook events as they arrive:

```bash
AGENTIRA_DAEMON_LOG_LEVEL=DEBUG python -m agents.daemon
```

Look for lines like:
```
[INFO]  agentira_daemon.webhook: Webhook receiver listening on port 9111
[INFO]  agentira_daemon.webhook: Webhook received: event=task.moved task_id=abc123
[INFO]  agentira_daemon: Woken by webhook — draining 1 queued event(s)
[INFO]  agentira_daemon: Picked todo task: abc123 — Add login page
```

### Event reference

| Event | Fired when | Who receives it |
|---|---|---|
| `task.assigned` | Task assigned to bot | The assigned bot |
| `task.moved` | Task status changes | The task's assignee |
| `task.commented` | Comment added to task | The task's assignee |
| `task.created` | New task created in project | All bot members of the project |
| `task.updated` | Task metadata changed | The task's assignee |
| `project.updated` | Project name/description changed | All bot members of the project |
| `project.member.add` | Bot added to a project | The added bot |

---

## 12. Troubleshooting

### Agent not picking up tasks

- Check the cron job is configured and last-ran recently (ZeroClaw Cron page)
- Verify the bot is a member of the project: `GET /api/projects/<id>/members`
- Check the bot's API key is valid: `zeroclaw agent -m "Call agentira__get_me"` in bot's workspace
- Check MCP server is reachable: `curl http://localhost:8000/sse`

### MCP connection errors

```bash
# Test SSE connection with auth
curl -H "Authorization: Bearer <bot-api-key>" http://localhost:8000/sse
# Should return: event: endpoint\ndata: /messages/...
```

Check `C:/agentira/mcp_server.log` for authentication errors.

### ZeroClaw daemon won't start

```bash
# Check if port is already in use
netstat -ano | findstr :3001

# Start with verbose logging
ZEROCLAW_WORKSPACE=~/.zeroclaw-agents/arch-bot zeroclaw daemon --port 3001
```

### Agent using wrong identity

Each agent should see itself when calling `get_me`. Verify the API key in
`~/.zeroclaw-agents/<bot-name>/config.toml` matches the bot's key in Agentira:

```bash
curl -H "Authorization: Bearer <api-key>" http://localhost:8000/sse
# If valid, you'll see SSE stream. If invalid, 401 error.
```

### Build errors (source build)

```bash
# Check Rust version
rustc --version   # needs 1.87+

# Update Rust
rustup update stable

# Clean rebuild
cd /path/to/zeroclaw
cargo clean
./bootstrap.sh --force-source-build
```

---

## Quick Reference

```
Agentira REST API:  http://localhost:8111
Agentira MCP:       http://localhost:8000/sse
Agentira UI:        http://localhost:3111

Per-agent dashboards:
  arch-bot:         http://localhost:3001
  frontend-bot:     http://localhost:3002
  qa-bot:           http://localhost:3003

Agent workspaces:   ~/.zeroclaw-agents/<bot-name>/config.toml
Agents IPC db:      ~/.zeroclaw-agents/agents.db
Agentira DB:        C:/agentira/data/agentira.db
MCP Server log:     C:/agentira/mcp_server.log
```
