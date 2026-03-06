# Agentira + ZeroClaw — System Architecture

## Overview

Agentira is the **coordination layer** — it manages projects, tasks, teams, RBAC, and the audit trail.
ZeroClaw is the **execution layer** — it runs AI agents that autonomously pick up and complete tasks.
The two are connected via the **Agentira MCP Server**, which exposes all task management tools over the Model Context Protocol.

---

## Full System Diagram

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                            HUMAN LAYER                                          ║
║                                                                                  ║
║   Browser / Human User                                                           ║
║   ┌──────────────────────┐    ┌─────────────────────────────────────────────┐   ║
║   │  Agentira Frontend   │    │     ZeroClaw Agent Dashboard (per agent)    │   ║
║   │  http://localhost:   │    │     http://localhost:3001  (arch-bot)       │   ║
║   │  3111                │    │     http://localhost:3002  (frontend-bot)   │   ║
║   │                      │    │     http://localhost:300N  (...)            │   ║
║   │  • Kanban Board      │    │                                             │   ║
║   │  • Task Management   │    │  • AgentChat  (talk to the agent directly)  │   ║
║   │  • Team Members      │    │  • Cron Jobs  (scheduled task polling)      │   ║
║   │  • Activity Feed     │    │  • Memory     (agent's knowledge base)      │   ║
║   │  • Notifications     │    │  • Cost       (API spend tracking)          │   ║
║   │  • /agents page ─────┼────┼► Agent cards + live status + dashboard link │   ║
║   └──────────┬───────────┘    └──────────────────────┬──────────────────────┘   ║
╚══════════════╪══════════════════════════════════════════╪════════════════════════╝
               │ REST API                                 │ WebSocket (chat)
               │                                          │ Pairing token auth
╔══════════════╪══════════════════════════════════════════╪════════════════════════╗
║              ▼                  AGENTIRA CORE           │                        ║
║   ┌──────────────────────────────────────────┐          │                        ║
║   │   Agentira REST API   :8111              │          │                        ║
║   │                                          │          │                        ║
║   │  /api/projects    /api/tasks             │          │                        ║
║   │  /api/profiles    /api/notifications     │          │                        ║
║   │  /api/board       /api/attachments       │          │                        ║
║   │  /api/service-accounts  /api/activity    │          │                        ║
║   └────────────────────┬─────────────────────┘          │                        ║
║                        │ shared services layer           │                        ║
║   ┌────────────────────▼─────────────────────┐          │                        ║
║   │   Agentira MCP Server  :8000             │          │                        ║
║   │                                          │          │                        ║
║   │  Transport:  SSE  →  /sse               │          │                        ║
║   │              HTTP →  /messages/          │          │                        ║
║   │                                          │          │                        ║
║   │  Auth:  Bearer <bot_api_key>             │          │                        ║
║   │                                          │          │                        ║
║   │  Tools exposed:                          │          │                        ║
║   │  • login / get_me                        │          │                        ║
║   │  • list_projects / create_project        │          │                        ║
║   │  • list_tasks / get_task / create_task   │          │                        ║
║   │  • move_task / update_task / delete_task │          │                        ║
║   │  • add_comment / get_activity            │          │                        ║
║   │  • add_project_member                    │          │                        ║
║   │  • get_notifications / mark_read         │          │                        ║
║   │  • upload_attachment / list_attachments  │          │                        ║
║   │  • list_statuses / list_roles            │          │                        ║
║   └────────────────────┬─────────────────────┘          │                        ║
║                        │ SQLite DB (data/agentira.db)   │                        ║
║   ┌────────────────────▼─────────────────────┐          │                        ║
║   │   Agentira Database                      │          │                        ║
║   │   • Projects  • Tasks    • Profiles      │          │                        ║
║   │   • Activity  • Notifications  • RBAC    │          │                        ║
║   └──────────────────────────────────────────┘          │                        ║
╚══════════════════════════════════════════════════════════╪════════════════════════╝
                                                           │
╔══════════════════════════════════════════════════════════╪════════════════════════╗
║                    ZEROCLAW AGENT LAYER                  │                        ║
║                                                          │                        ║
║  ┌───────────────────────────────────────────────────────▼─────────────────────┐ ║
║  │  ZeroClaw Daemon — arch-bot                                                 │ ║
║  │  ZEROCLAW_WORKSPACE=~/.zeroclaw-agents/arch-bot                             │ ║
║  │                                                                             │ ║
║  │  ┌─────────────┐  ┌──────────────────────────────────┐  ┌───────────────┐  │ ║
║  │  │   Provider   │  │   MCP Client (Agentira tools)   │  │ Cron Scheduler│  │ ║
║  │  │              │  │                                  │  │               │  │ ║
║  │  │ • Anthropic  │  │  Transport: SSE                  │  │ */2 * * * *   │  │ ║
║  │  │ • OpenRouter │  │  URL: http://127.0.0.1:8000/sse  │  │ "Check tasks  │  │ ║
║  │  │ • OpenAI     │  │  Auth: Bearer <arch-bot-api-key> │  │  assigned to  │  │ ║
║  │  │ • Ollama     │  │                                  │  │  me and work  │  │ ║
║  │  │ • Gemini     │  │  Tools available to LLM:         │  │  on the most  │  │ ║
║  │  │ • Mistral    │  │  agentira__list_tasks            │  │  urgent one"  │  │ ║
║  │  │ • ...any     │  │  agentira__move_task             │  │               │  │ ║
║  │  └──────┬───────┘  │  agentira__add_comment           │  └───────────────┘  │ ║
║  │         │          │  agentira__create_task            │                     │ ║
║  │         │          │  ...etc                           │                     │ ║
║  │         │          └──────────────────────────────────┘                     │ ║
║  │  ┌──────▼──────────────────────────────────────────────────────────────┐    │ ║
║  │  │  Agent Loop (loop_.rs)                                              │    │ ║
║  │  │                                                                     │    │ ║
║  │  │  1. Receive prompt (from cron / chat / channel)                    │    │ ║
║  │  │  2. Call LLM with system prompt + available tools                  │    │ ║
║  │  │  3. Execute tool calls → results back to LLM                       │    │ ║
║  │  │  4. Loop until task complete (max_tool_iterations = 20)            │    │ ║
║  │  │  5. Human approval gate (supervised mode, if configured)           │    │ ║
║  │  └─────────────────────────────────────────────────────────────────────┘    │ ║
║  └─────────────────────────────────────────────────────────────────────────────┘ ║
║                                                                                  ║
║  ┌─────────────────────────────────────────────────────────────────────────────┐ ║
║  │  ZeroClaw Daemon — frontend-bot                                             │ ║
║  │  (same structure, different workspace + API key + port)                     │ ║
║  └─────────────────────────────────────────────────────────────────────────────┘ ║
║                                                                                  ║
║  ┌─────────────────────────────────────────────────────────────────────────────┐ ║
║  │  Agents IPC  (shared SQLite: ~/.zeroclaw-agents/agents.db)                  │ ║
║  │  • All agent processes register here                                         │ ║
║  │  • Agents can discover + message each other                                  │ ║
║  │  • Enables delegation: arch-bot can spawn subtask for frontend-bot           │ ║
║  └─────────────────────────────────────────────────────────────────────────────┘ ║
╚══════════════════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════════════════╗
║                         SETUP AGENT LAYER                                       ║
║                                                                                  ║
║  agents/setup_zeroclaw.py   (run by human via Claude Code or CLI)                ║
║                                                                                  ║
║  1. Connect to Agentira REST API → list projects + bot profiles                  ║
║  2. Human selects: project, bots, provider, API key, deployment mode             ║
║  3. For each bot:                                                                ║
║     a. Create workspace dir  ~/.zeroclaw-agents/<bot-name>/                      ║
║     b. Generate config.toml  (provider + MCP + cron + port)                     ║
║     c. Spawn zeroclaw daemon --port <N>  OR  docker run  OR  ssh deploy          ║
║  4. Return: agent dashboard URLs + pairing codes for human                       ║
║                                                                                  ║
║  Deployment targets:                                                             ║
║  • Local          → zeroclaw daemon process                                      ║
║  • Docker         → docker-compose per agent                                     ║
║  • Remote/Cloud   → SSH + zeroclaw daemon on remote host                         ║
╚══════════════════════════════════════════════════════════════════════════════════╝
```

---

## Data & Auth Flow

```
Human creates bot in Agentira UI
        │
        ▼
POST /api/service-accounts  →  { name, api_key }
        │
        ▼
Setup Agent reads api_key
        │
        ▼
Writes to config.toml:
  [mcp.servers]
  name = "agentira"
  transport = "sse"
  url = "http://127.0.0.1:8000/sse"
  headers = { Authorization = "Bearer <api_key>" }
        │
        ▼
ZeroClaw daemon starts → MCP handshake → tools loaded
        │
        ▼
Cron fires → agent calls list_tasks (as itself) → works on assigned tasks
        │
        ▼
All actions logged in Agentira activity feed
Human watches progress in Agentira UI + can chat via ZeroClaw AgentChat
```

---

## Deployment Modes

```
┌─────────────────────────────────────────────────────────────────────┐
│  MODE 1: Local Development                                          │
│                                                                     │
│  All services on one machine                                        │
│  Agentira  → localhost:8111 / :8000 / :3111                        │
│  Agents    → localhost:3001, :3002, :300N                           │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  MODE 2: Docker Compose (Self-Hosted)                               │
│                                                                     │
│  agentira-backend:8111                                              │
│  agentira-mcp:8000                                                  │
│  zeroclaw-arch-bot:42617                                            │
│  zeroclaw-frontend-bot:42618                                        │
│  zeroclaw-N:4261N                                                   │
│                                                                     │
│  All on same Docker network → agents reach MCP via service name    │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  MODE 3: Cloud / Remote Server                                      │
│                                                                     │
│  Agentira Backend → cloud VM / VPS (public IP or private network)  │
│  Agent Processes  → same VM  OR  separate VMs per agent            │
│  Human Access     → reverse proxy (nginx/caddy) + HTTPS            │
│  Agent Dashboard  → per-agent subdomain or path prefix             │
│                     e.g. https://agents.myco.ai/arch-bot           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Continuous Execution: Push Notification + Activity Poll

Starting from the ZeroClaw daemon integration, agents are notified of platform activity
through a hybrid mechanism so they react instantly rather than waiting for the next cron
cycle.

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                    NOTIFICATION FLOW (ADR-007)                                   ║
║                                                                                  ║
║  Agentira Backend (services.py)                                                  ║
║  ┌────────────────────────────────────────────────────────────────────────────┐  ║
║  │  Event occurs:                  agent_notifier.py                          │  ║
║  │  • task.assigned   ─────────────────────────────────► POST /webhook        │  ║
║  │  • task.moved                   notify(webhook_url,    to each bot's       │  ║
║  │  • task.commented               event, task, actor)    webhook_url         │  ║
║  │  • task.created    (NEW)                                     │              │  ║
║  │  • project.updated (NEW)        notify_many(targets,         │              │  ║
║  │  • project.member.add (NEW)     event, payload, actor)       │              │  ║
║  │                                                               │              │  ║
║  │  GET /api/activity/mine?actor=bot&since=<ts>  ◄── poll fallback             │  ║
║  │  Returns: all activity on bot's tasks + projects since ts                  │  ║
║  └───────────────────────────────────────────────────────────────┬────────────┘  ║
╚══════════════════════════════════════════════════════════════════╪════════════════╝
                                                                   │
                  push (instant, sub-second)     ◄─────────────────┘
                  poll fallback (every N sec)    ◄── GET /api/activity/mine
                                  │
╔══════════════════════════════════╪═════════════════════════════════════════════════╗
║              AGENTIRA DAEMON     │                                                 ║
║  ┌───────────────────────┐       │                                                 ║
║  │  WebhookReceiver      │       │                                                 ║
║  │  (stdlib http.server) │       │                                                 ║
║  │  port: 9111           │       │                                                 ║
║  │                       │       │                                                 ║
║  │  POST /webhook        │◄──────┘                                                 ║
║  │  ├── validate token   │                                                         ║
║  │  ├── queue.put(event) │                                                         ║
║  │  └── wake_event.set() ├──► threading.Event                                      ║
║  └───────────────────────┘          │                                              ║
║                                     ▼                                              ║
║  ┌────────────────────────────────────────────────────────────────────────────┐    ║
║  │  AgentiraDaemon main loop                                                  │    ║
║  │                                                                            │    ║
║  │  wake_event.wait(timeout=poll_interval)  ← interrupted by webhook OR      │    ║
║  │       │                                    fires after interval expiry     │    ║
║  │       ▼                                                                    │    ║
║  │  drain event queue → log immediate context                                 │    ║
║  │       │                                                                    │    ║
║  │  [hybrid/poll mode]                                                        │    ║
║  │  get_activity_mine(since=last_poll_ts) → catch missed events               │    ║
║  │       │                                                                    │    ║
║  │  poll_and_execute()                                                        │    ║
║  │  ├── list tasks in_progress → execute highest priority                     │    ║
║  │  ├── list tasks todo        → move to in_progress, execute                 │    ║
║  │  └── list tasks backlog     → fallback                                     │    ║
║  └────────────────────────────────────────────────────────────────────────────┘    ║
╚═════════════════════════════════════════════════════════════════════════════════════╝

Notification modes (AGENTIRA_DAEMON_NOTIFICATION_MODE):
  hybrid  — webhook receiver + activity poll fallback (default, recommended)
  webhook — receiver only, no fallback poll
  poll    — no receiver, pure polling (for NAT/firewall environments)
```

### Webhook Payload Schema

Every event fired by the backend uses structured fields only. There is no pre-composed
`message` string — task titles and comments are user-supplied content that must never
be passed raw to an LLM (prompt injection risk). The daemon constructs its own
sanitised context from these fields when building prompts.

```json
{
  "event":      "task.moved",
  "task_id":    "abc123",
  "task_title": "Add login page",
  "project_id": "xyz789",
  "status":     "review",
  "priority":   "high",
  "actor":      "alice",
  "timestamp":  "2026-03-06T18:00:00+00:00"
}
```

For project-level events (`project.updated`, `project.member.add`), `task_id` is
omitted and `project_id` is the primary identifier.

### Webhook Subscription Config

Which events dispatch and to whom is controlled by subscription rules in the daemon's
YAML config — not hardcoded in the backend. Default is bots only. Rules can restrict
or expand receivers per event type:

```yaml
webhook:
  subscriptions:
    - event: task.assigned
      receivers: [self]      # assignee only
    - event: task.created
      receivers: bots        # all bot-role project members
    - event: project.updated
      receivers: bots
```

### Notification Poll Fallback

The poll fallback path reuses the **existing** notification system — no new endpoint
needed. The daemon calls `GET /api/notifications?actor=bot&unread_only=true` and marks
each notification read after processing. MCP-based agents (ZeroClaw) use the equivalent
`agentira__get_notifications` MCP tool on their own cron cycle.

---

## AI Factory Pattern

When multiple agents collaborate on a project, they form a **factory pipeline**:

```
Project Task Board
        │
        ├── backlog ──► Architect Bot   → designs + breaks down tasks
        │                   │
        │                   ▼ creates sub-tasks for other bots
        │
        ├── in_progress ──► Frontend Bot  → implements UI tasks
        │                   Backend Bot   → implements API tasks
        │                   QA Bot        → reviews + opens bug tasks
        │
        └── review ──────► Human User    → approves + merges
                           Architect Bot → final sign-off

Coordination:
  • Each bot polls for tasks assigned to it (via MCP list_tasks)
  • Agents IPC allows direct bot-to-bot messaging
  • Architect bot can delegate via Agentira task assignment
  • All progress visible in Agentira Kanban + activity feed
```
