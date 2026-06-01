<div align="center">

# Agentira

**A self-hosted platform for orchestrating AI coding agents on real software projects.**

You don't talk to a model — you run a small team of AI agents (Planner, Implementers, Reviewer, DevOps, plus an orchestrator Conductor) against your repos, with traceable runs, verifiable artifacts, and a Kanban board that reflects reality.

[Getting Started](docs/getting-started.md) · [Deployment](docs/deployment.md) · [Architecture](docs/architecture.md) · [ADRs](docs/architecture_decision_record.md) · [Vision](AGENTIRA_VISION.md)

</div>

---

## What this is, in 30 seconds

You sign in. A workspace already has six agents — Conductor, Planner, Backend / Frontend Implementer, Reviewer, DevOps — each with a tunable persona and an MCP toolkit. You create a project, drop a brief or design, hit **Run** on the auto-generated "Plan this project" task. The Conductor reads your brief, picks a stack, breaks the work into 3–8 child tasks, and registers a one-page plan as an artifact. You assign tasks to the right agent, hit Run, and they edit code in their own git worktrees, commit, open PRs, and finish with a verdict you can verify. You see everything on the board: status, diff, artifacts, conversation, tokens, cost.

**Why this exists.** Cursor and Claude Code are great when you're watching the screen. Agentira is for the time you're *not* watching — overnight, in meetings, on the move. It trades "every keystroke is yours" for "every run produces evidence, every transition is gated, and the board reflects reality."

---

## Two products under one umbrella

| | What | Routes |
|---|---|---|
| **Flowty Studio** | Workspace, projects, tasks, board, attachments, comments, activity | `/` |
| **Flowty Forge** | Agent orchestration: agents, runs, conversations, dispatch | `/forge/*` |

Same login, same workspace, same database. Two products because they're two distinct mental models — running a board vs. running a team of agents — and you only want to think about one at a time.

---

## Architecture, in one picture

```
              ┌──────────────────────────────────────┐
              │           Browser (React)            │
              │     Flowty Studio + Flowty Forge     │
              └──────────────┬───────────────────────┘
                             │ HTTPS / WebSocket
                             ▼
              ┌──────────────────────────────────────┐
              │     Backend  (FastAPI, Postgres)     │
              │   • REST API  (humans)               │
              │   • MCP server (agents)              │
              │   • Conversations / Turns / Runs     │
              │   • Gate engine, sandbox resolver    │
              └──────────────┬───────────────────────┘
                             │ WebSocket (dispatch frames)
                             ▼
              ┌──────────────────────────────────────┐
              │      Daemon  (on the user's box)     │
              │   • Receives dispatch                │
              │   • Spawns the runtime (claude CLI)  │
              │   • Owns git worktrees + logs        │
              │   • Streams events back              │
              └──────────────┬───────────────────────┘
                             │ subprocess
                             ▼
              ┌──────────────────────────────────────┐
              │  Runtime  (claude CLI, openclaw, …)  │
              │   Edits files. Commits. Opens PRs.   │
              └──────────────────────────────────────┘
```

Backend + frontend live in the cloud. **The daemon and the runtime live on the user's own machine** — because that's where the code is. The cloud coordinates; the laptop executes.

See [docs/architecture.md](docs/architecture.md) for the deep dive.

---

## Three layered concepts (ADR 009)

Every dispatch funnels through three concepts:

| Concept | What it is | Lifetime |
|---|---|---|
| **Conversation** | The agent's working memory for one *scope* (`task:T`, `chat:project:P`, `chat:default`). What `claude --resume` keys off. | Per (agent, scope) — long-lived. |
| **Turn** | One dispatch (user message + agent reply, single `trace_id`). The atomic, always-durable, always-stoppable unit. | Per dispatch. |
| **Run** | An *emergent span* grouping the turns of one work episode. Carries verdict, accounting, diff, artifacts. | Per work episode — may span many turns. |

A turn becomes a Run when it produces work (per the project's [work-signal mode](docs/getting-started.md#7-what-counts-as-a-run)). Free chat that does nothing stays a turn; a turn that touches files becomes a Run automatically.

The full reasoning lives in [docs/architecture_decision_record.md → ADR 009](docs/architecture_decision_record.md).

---

## Features

### For the human

| Feature | Status | Detail |
|---|---|---|
| Projects, board, Kanban, RBAC, members | ✅ shipped | |
| Project creation wizard | ✅ shipped (AP-153) | 4-step: basics → attachments → initial tasks → agents |
| Project-level attachments (briefs, designs, brand guides) | ✅ shipped (AP-152) | Drag-drop on project dashboard. Agents read text inline, fetch binaries with their API key. |
| Default agent templates (Conductor + 5 others) | ✅ shipped (AP-157) | Seeded from `templates/agents/<name>.yaml` + `.md` pairs. User owns every prompt after first edit. |
| Comments → wake assigned agent | ✅ shipped | Commenting on a task dispatches the agent into the task scope. |
| Auto-kickoff "Plan this project" task | ✅ shipped (AP-150) | Conductor auto-assigned at project create. |
| Tasks: epics, priorities, DoD, due dates, multi-repo | ✅ shipped (AP-154) | A task declares which of the project's repos it touches. |
| Markdown rendering for descriptions | ✅ shipped (AP-39) | Shared component for epic + task + (future) project + run summary. |
| Roadmap / timeline view | ✅ shipped | Group by epic / status / assignee. |
| Notifications (push + poll hybrid, ADR-007) | ✅ shipped | Bell icon, inbox, mark-read. |
| Activity log (every action, tamper-evident) | ✅ shipped | |
| OAuth (Google / GitHub) + username/password | ✅ shipped | |

### For the agent

| Feature | Status | Detail |
|---|---|---|
| MCP server with ~40 tools | ✅ shipped | `create_task`, `update_task`, `add_comment`, `list_project_attachments`, `read_attachment_text`, `register_run_artifact`, `finish_run`, `get_run`, `list_runs`, etc. |
| Runtime adapter contract (claude, openclaw, …) | ✅ shipped (AP-86 / #86) | Capability flags: `RESUME`, `STREAM_EVENTS`, `STOP`, `PAUSE`, `TOOLS`, `MCP`. |
| Stable per-(agent, task) cwd for `--resume` | ✅ shipped (ADR 009) | The worktree inside is ephemeral per Run; the cwd persists. |
| Per-run git worktree + log dir | ✅ shipped | `~/.agentira/runs/<id>/{stdout.log,stderr.log,meta.json}` |
| Chat-during-run pause / steer / resume | ✅ shipped (ADR 009 D) | Mid-run comment parks, captures session, resumes with the steer as next turn. |
| Run / Turn shadow registration | ✅ shipped (AP-151) | Run row reserved at dispatch so logs + artifacts have a home before work happens; deleted at completion if no work crystallized. |
| Artifact registration (`pr`, `commit`, `file`, `log`, `report`, `url`) | ✅ shipped (AP-125) | Capped, deduplicated, structured. |
| Restart button on terminal runs | ✅ shipped | Same (task, agent); fresh dispatch with prior-outcome context. |
| Sandbox containment (config Phase 1) | ✅ shipped (AP-155 P1) | Per-agent + per-project mode dropdown (off / cwd / strict / container). Dispatch logs the resolved mode; Phase 2 wires per-adapter enforcement. |

### Platform / safety

| Feature | Status | Detail |
|---|---|---|
| Gate engine (column-exit checks) | ✅ shipped (AP-158 P1) | Per-project opt-in. Enforces evidence at transitions: DoD before todo, branch/PR before review, all DoD checked + PR linked before done. Structured 422 with `failed_gates`. |
| Conductor autonomous mode | ✅ shipped (AP-80) | Queue tick, planning turn, daily report — all cadence-configurable on the agent's own profile. |
| Workspace agent templates (YAML + Markdown) | ✅ shipped (AP-157) | Drop new templates into `templates/agents/`; restart picks them up. Set-if-empty seeding — user's edits survive. |
| Auto-retry on transient crashes | ✅ shipped (AP-149) | Subprocess crash mid-run resumes the session automatically. |
| Restart-proof inflight registry | ✅ shipped (ADR 009 B) | In-flight turns survive backend restart; orphan reaper kills zombies. |
| Stale-run reconciliation | ✅ shipped | Periodic sweep for runs whose daemon vanished. |
| Push + poll notifications (ADR-007) | ✅ shipped | |
| Project + Agent sandbox modes | ✅ shipped (AP-155) | Project mode overrides agent default; resolver downshifts to what the adapter supports. |
| Multi-repo task declaration | ✅ shipped (AP-154) | Backend / frontend / shared repos all listed under one project; tasks pick a subset. |
| Webhooks (per project, configurable rules) | ✅ shipped | |
| Templates (YAML-defined project workflows) | 🟡 partial | `templates/production-readiness.yaml` ships; gate engine Phase 1 honors local gates. Phase 2 wires GitHub-Actions check_runs into `ci_passing` / `pr_merged` / `reviewer_approved`. |

### On the roadmap

- One-click daemon installers for Mac (`.pkg`), Windows (`.msi`), Linux (`curl | sh`).
- Sandbox enforcement Phase 2 (bubblewrap on Linux, sandbox-exec on Mac, Docker container per agent).
- Multi-repo materializer Phase 2 (worktree every declared repo into the agent cwd as named subdirs).
- Agentira-dog-fooding-Agentira (AP-160): flip the autonomy switch on this very repo's backlog.
- Audited escape-hatch MCP tool for path access outside the sandbox.
- Attachment object storage (Railway Volume or S3) for production deployments.

See the [board](https://github.com/gitmaster3000/agentira) for live status.

---

## Quick start — local development

> **For deploying to Railway**, skip to [docs/deployment.md](docs/deployment.md).

### Prerequisites

- Docker + Docker Compose
- Node.js 18+ (only if you want to run the frontend outside Docker)
- A second clone of `agentira-frontend` as a **sibling directory**:
  ```
  flowty/
  ├── agentira/          ← this repo
  └── agentira-frontend/ ← UI repo (https://github.com/gitmaster3000/agentira-frontend)
  ```
  `docker-compose.yml`'s frontend service references `../agentira-frontend` relatively.

### Bring it up

```bash
docker compose up -d
```

That starts four services on the **dev** profile:

| Service | URL | What |
|---|---|---|
| frontend | http://localhost:3111 | Vite dev server, HMR |
| backend | http://localhost:8111 | FastAPI, uvicorn `--reload` |
| mcp | http://localhost:8000 | MCP server for agents |
| postgres / sqlite | (dev uses SQLite at `data/agentira.db`) | |

Sign in at `http://localhost:3111` — default admin is `admin / admin123` on a fresh DB. The six default agents (Conductor, Planner, Backend / Frontend Implementer, Reviewer, DevOps) are seeded at first boot.

### Run the daemon (so agents can actually do work)

```bash
pip install -e agentira-cli/
agentira daemon
```

The daemon connects to `ws://localhost:8111/api/forge/daemon/ws`, registers any claude CLI it finds on `PATH`, and waits for dispatch frames. Open a project, hit Run on a task, watch the events stream into the Run page.

### Multi-environment compose

Three explicit environments, **all three run simultaneously** on one host (distinct ports + isolated compose project names so they don't collide).

| Env | Frontend | Backend | MCP | DB | Hot reload | Compose project |
|---|---|---|---|---|---|---|
| **dev** | 3111 | 8111 | 8000 | SQLite | ✅ | `agentira` (default) |
| **qa** | 3112 | 8112 | 8001 | Postgres | ❌ | `agentira-qa` |
| **prod** | 3113 | (internal) | (internal) | Postgres | ❌ | `agentira-prod` |

```bash
# Dev (auto-loads docker-compose.override.yml)
docker compose up -d

# QA alongside dev
docker compose -p agentira-qa \
  -f docker-compose.yml -f docker-compose.qa.yml \
  --env-file .env.qa up -d

# Prod alongside both
docker compose -p agentira-prod \
  -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file .env.prod up -d
```

For qa / prod, copy the `.env.{qa,prod}.example` file and fill in `JWT_SECRET` (`openssl rand -hex 32`) + `POSTGRES_PASSWORD`. The compose files refuse to start if these are missing.

---

## Deploying to Railway (or anywhere with Postgres + Docker)

Full walkthrough: [docs/deployment.md](docs/deployment.md). The short version:

1. Provision Railway project + Postgres add-on.
2. Deploy three services from the same repo with different Dockerfiles: `Dockerfile` (backend), `Dockerfile.mcp` (mcp), and `agentira-frontend/Dockerfile` (frontend).
3. Wire `${{Postgres.DATABASE_URL}}` + `${{backend.JWT_SECRET}}` into MCP via Railway variable references.
4. Mount a 1GB Volume on backend `/app/data` so attachments survive redeploys.
5. Update `agentira-frontend/nginx.conf`'s `proxy_pass` to match your backend service name.

Migrations run automatically at startup (`scripts/bootstrap_db.py` → `init_db()`), idempotent on both SQLite and Postgres.

---

## Connecting AI agents (MCP)

Any MCP-aware client (Claude Desktop, Cursor, Antigravity, etc.) can talk to the workspace as either a user or an agent.

### HTTP / Bearer (recommended)

```json
{
  "mcpServers": {
    "agentira": {
      "serverUrl": "http://127.0.0.1:8111/mcp",
      "headers": { "Authorization": "Bearer YOUR_API_KEY" }
    }
  }
}
```

Your API key is at **top-right avatar → Settings → API key**. The MCP server uses it to identify which user/agent is calling and to enforce RBAC on every tool.

### Stdio (fallback for clients that don't support HTTP)

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

### Tool surface

Roughly forty MCP tools across:

- **Workspace inspection**: `list_projects`, `get_project`, `list_tasks`, `get_task`, `get_activity`, `list_epics`, `get_me`, `get_my_involvement`
- **Mutation**: `create_project`, `create_task`, `update_task`, `move_task`, `add_comment`, `add_project_member`, `create_epic`, `update_epic`
- **Attachments**: `list_project_attachments`, `read_attachment_text`, `list_attachments`, `upload_attachment`, `download_attachment`
- **Runs (for the agent itself)**: `register_run_artifact`, `finish_run`, `get_run`, `get_run_events`, `get_run_diagnostics`, `list_permissions`, `list_statuses`, `list_roles`
- **Notifications**: `get_notifications`, `mark_notification_read`

Every tool is RBAC-checked against the API key's profile. Service accounts (api-key-only, no runtime) live in Settings → Service Accounts; managed agents live in Forge → Agents.

---

## Repository layout

```
agentira/
├── backend/                       # FastAPI app
│   ├── rest_api.py                # /api/* router mounting
│   ├── mcp_server.py              # MCP tool definitions
│   ├── services.py                # Studio business logic
│   ├── attachments.py             # AP-152 attachments domain
│   ├── agent_templates.py         # AP-157 template loader
│   ├── gates.py                   # AP-158 transition gates
│   ├── sandbox.py                 # AP-155 sandbox resolver
│   ├── auth.py                    # RBAC + check_transition
│   ├── notifications.py           # ADR-007 broker
│   ├── jwt_auth.py
│   ├── db.py                      # engine + dialect-aware migrations
│   ├── models.py                  # core SQLAlchemy models
│   └── forge/                     # Flowty Forge — self-contained
│       ├── router.py              # /api/forge/* routes
│       ├── services.py            # dispatch_trigger, complete_trigger, …
│       ├── models.py              # Agent, Run, AgentMessage, Conversation, …
│       ├── conductor.py           # orchestrator agent + queue tick
│       ├── ws_dispatch.py         # daemon WebSocket hub
│       ├── runtimes/              # adapter contract + claude / openclaw impls
│       ├── turns.py               # work-signal modes, crystallize
│       ├── live_inflight.py       # in-memory + on-disk inflight registry
│       └── mcp_registry.py        # MCP server registry + merge
├── agentira-cli/                  # CLI + daemon entry point (`agentira daemon`)
├── templates/
│   ├── agents/                    # AP-157 default agent templates (yaml + md)
│   └── production-readiness.yaml  # project-workflow template (gate engine fodder)
├── scripts/
│   ├── bootstrap_db.py            # called at container start
│   └── ...
├── docs/
│   ├── getting-started.md         # first-user walkthrough
│   ├── deployment.md              # Railway click-through
│   ├── architecture.md            # the deep dive
│   ├── architecture_decision_record.md  # ADRs (ADR 009 is the big one)
│   ├── conversations.md
│   ├── git_integration.md
│   ├── rbac_guide.md
│   └── ...
├── tests/                         # legacy test root (will fold into backend/tests over time)
├── backend/tests/                 # canonical test home
├── data/                          # volume-mounted: agentira.db (dev), attachments/
├── docker-compose.yml             # base — required env override
├── docker-compose.override.yml    # dev (auto-loaded)
├── docker-compose.qa.yml
├── docker-compose.prod.yml
├── Dockerfile                     # backend
├── Dockerfile.mcp                 # MCP server
├── railway.toml                   # Railway backend service config
├── PRE_RELEASE_AUDIT.md           # current readiness snapshot
├── CLAUDE.md                      # code-conventions for AI agents working in this repo
├── AGENTIRA_VISION.md             # north star
└── README.md                      # you are here
```

`backend/forge/` is **self-contained**. Real foreign keys between modules, no string workarounds. New features live in their own focused module (`backend/<domain>.py`), not appended to `services.py`. See [CLAUDE.md](CLAUDE.md) for the full conventions list.

---

## Tech stack

| Layer | Stack |
|---|---|
| Backend | FastAPI · SQLAlchemy 2 · Pydantic · uvicorn |
| Database | SQLite (dev) · Postgres 16 (qa / prod) |
| Tests | pytest · 280+ unit + integration tests |
| MCP | `fastmcp` (HTTP + Stdio transports) |
| Frontend | React 18 · Vite 6 · TailwindCSS · React-Router · react-markdown |
| WebSocket dispatch | `websockets` library, per-daemon hub |
| Auth | JWT (stateless) + Google / GitHub OAuth + username/password |
| Daemon | Python `click` CLI, asyncio WS client, subprocess management |
| Default runtime | `claude` CLI (`@anthropic-ai/claude-code`) |
| Other runtimes | OpenClaw (HTTP gateway, AP-87 spec), Codex / Gemini scaffolded |
| Deploy | Docker Compose · Railway (current target) · any K8s-compatible host (future) |

---

## Testing

```bash
# Run the full backend suite (inside the container)
docker exec agentira-backend-1 python -m pytest backend/tests/ -q
# → 280+ tests pass on main

# Specific suite
docker exec agentira-backend-1 python -m pytest backend/tests/test_gates.py -q

# Frontend type-check + build
cd ../agentira-frontend && npx vite build
```

Two pre-existing failures in `test_run_status_broadcast.py` (pytest-asyncio missing) and `test_template_loader.py` (pydantic v1 validators) are tracked but not blocking — they fail on `main` too.

---

## Conventions for contributors (and AI agents)

The full ruleset is in [CLAUDE.md](CLAUDE.md), but the short version:

- **Modular boundaries.** New domains get their own `backend/<domain>.py` (or `backend/forge/<domain>.py`). Functions over class hierarchies. Reach for OOP only when state or storage actually swaps.
- **Prompts-as-config.** Agent system prompts live on `Profile.system_prompt` (edited in Agent Settings UI). Task content lives on `Task.description` (edited in Task UI). No prompt text in dispatch code. No re-applying code constants on top of user-edited rows.
- **Surgical changes.** Touch only what the user's request needs. Don't refactor adjacent code. Match existing style.
- **Test what matters.** Every PR adds tests for the behavior it adds, regression-pins behavior it preserves.
- **CI must pass before merge.** Unit + integration smoke + compose-config validate are required.

---

## Project status

Today's snapshot lives in [PRE_RELEASE_AUDIT.md](PRE_RELEASE_AUDIT.md):

- Core platform is in working shape (280+ tests pass, dev/qa/prod compose profiles known-good).
- 9 backend PRs + 6 frontend PRs are queued and CI-green, adding the AP-152/153/154/155/157/158 feature set.
- First-user Railway deployment depends on those merges + an end-to-end smoke check + a one-click daemon installer (in roadmap).

The board is at [Agentira Platform / AP-*](https://github.com/gitmaster3000/agentira) and is the canonical source of truth for what's in flight.

---

## Acknowledgements

- The runs / turns / conversations model is shaped by the failure modes we hit dog-fooding Cursor and Claude Code on multi-day async work. ADR 009 is the post-mortem made architecture.
- The runtime adapter contract takes inspiration from how `claude --resume` and OpenClaw's `sessionKey` solve the same conversation-continuity problem from opposite directions.
- The MCP design follows the Model Context Protocol spec; thanks to the Anthropic + community work that makes "the agent's toolkit" a real abstraction.

---

<div align="center">

**Built for the moment you're not watching the screen.**

[Vision](AGENTIRA_VISION.md) · [Getting Started](docs/getting-started.md) · [Deployment](docs/deployment.md) · [Architecture](docs/architecture.md) · [Conventions](CLAUDE.md)

</div>
