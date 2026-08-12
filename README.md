<div align="center">

# Agentira

**A self-hosted platform for orchestrating AI coding agents on real software projects.**

You don't talk to a model — you run a small team of AI agents (Planner, Implementers, Reviewer, DevOps, plus an orchestrator Conductor) against your repos, with traceable runs, verifiable artifacts, and a Kanban board that reflects reality.

**[Documentation](https://gitmaster3000.github.io/agentira-oss-docs/)**

[Install](https://gitmaster3000.github.io/agentira-oss-docs/user-guide/install) · [Getting started](https://gitmaster3000.github.io/agentira-oss-docs/user-guide/first-project) · [Deployment](https://gitmaster3000.github.io/agentira-oss-docs/technical/deployment) · [Architecture](https://gitmaster3000.github.io/agentira-oss-docs/technical/architecture) · [Contributing](CONTRIBUTING.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

</div>

---

## What this is, in 30 seconds

You sign in. A workspace already has seven agents — Conductor, Planner, Backend / Frontend Implementer, Reviewer, DevOps, and a Guide — each with a tunable persona and an MCP toolkit. You create a project, drop a brief or design, hit **Run** on the auto-generated "Plan this project" task. The Conductor reads your brief, picks a stack, breaks the work into 3–8 child tasks, and registers a one-page plan as an artifact. You assign tasks to the right agent, hit Run, and they edit code in their own git worktrees, commit, open PRs, and finish with a verdict you can verify. You see everything on the board: status, diff, artifacts, conversation, tokens, cost.

**Why this exists.** Cursor and Claude Code are great when you're watching the screen. Agentira is for the time you're *not* watching — overnight, in meetings, on the move. It trades "every keystroke is yours" for "every run produces evidence, every transition is gated, and the board reflects reality."

---

## Architecture, in one picture

```
              ┌──────────────────────────────────────┐
              │           Browser (React)            │
              │         Agentira web interface       │
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

See the [architecture guide](https://gitmaster3000.github.io/agentira-oss-docs/technical/architecture) for the deep dive.

---

## Three layered concepts (ADR 009)

Every dispatch funnels through three concepts:

| Concept | What it is | Lifetime |
|---|---|---|
| **Conversation** | The agent's working memory for one *scope* (`task:T`, `chat:project:P`, `chat:default`). What `claude --resume` keys off. | Per (agent, scope) — long-lived. |
| **Turn** | One dispatch (user message + agent reply, single `trace_id`). The atomic, always-durable, always-stoppable unit. | Per dispatch. |
| **Run** | An *emergent span* grouping the turns of one work episode. Carries verdict, accounting, diff, artifacts. | Per work episode — may span many turns. |

A turn becomes a Run when it produces work (per the project's [work-signal mode](https://gitmaster3000.github.io/agentira-oss-docs/technical/concepts#work-signal-modes)). Free chat that does nothing stays a turn; a turn that touches files becomes a Run automatically.

The full reasoning lives in [Core concepts](https://gitmaster3000.github.io/agentira-oss-docs/technical/concepts).

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
| MCP server with 49 tools | ✅ shipped | `create_task`, `update_task`, `add_comment`, `create_attachment`, `read_attachment`, `register_run_artifact`, `finish_run`, `get_run`, `list_runs`, etc. |
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

See [Project status](#project-status) for where the board lives.

---

## Quick start — local development

> **For deploying to Railway**, skip to the [deployment guide](https://gitmaster3000.github.io/agentira-oss-docs/technical/deployment).

### Prerequisites

- Docker + Docker Compose — that's it for the stack itself.
- Python 3.11+ on your machine, for the daemon (it runs on your box, not in Docker).
- A coding runtime the daemon can drive: the [`claude` CLI](https://github.com/anthropics/claude-code), OpenClaw, Codex, or a local Ollama. At least one, or agents have nothing to execute with.
- Node.js 20+ only if you want to run the frontend outside Docker.

Dev needs **no `.env` file** — `docker-compose.override.yml` hardcodes dev values on purpose (dev credentials aren't secrets). `.env.example` is for qa/prod.

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
| postgres | localhost:5432 | Postgres 16 — same engine as prod, on purpose |

Sign in at `http://localhost:3111` — default admin is `admin / admin123` on a fresh DB. Seven agents (Conductor, Planner, Backend / Frontend Implementer, Reviewer, DevOps, Agentira Guide) are seeded at first boot.

**Signup is invite-only.** There is no open registration form: the first admin exists from bootstrap, and everyone else joins through an invite. Mint one from inside the backend container —

```bash
docker compose exec -e FRONTEND_URL=http://localhost:3111 backend \
  python scripts/create_invite.py --role admin          # new org, invitee becomes its admin
#                                 --role member --org <org_id>   # joins your org
```

— and send the printed `/signup?invite=…` link.

### Run the daemon (so agents can actually do work)

```bash
pip install -e agentira-cli/
agentira daemon login --api-url http://localhost:8111   # opens the browser, sign in as admin
agentira daemon start
```

`agentira daemon` on its own is a command group — `login` then `start` is the sequence. Check it with `agentira daemon status` and `agentira daemon logs`.

The daemon connects to `ws://localhost:8111/api/forge/daemon/ws`, registers every runtime it finds on `PATH`, and waits for dispatch frames. Open a project, hit Run on a task, watch the events stream into the Run page.

For a local stack you can skip the browser entirely — the dev compose profile ships a static daemon key:

```bash
AGENTIRA_DAEMON_API_URL=http://127.0.0.1:8111 \
AGENTIRA_DAEMON_API_KEY=dev-daemon-key-local-only \
  agentira daemon start
```

That shortcut is gated on `AGENTIRA_ENV=dev` in the backend and does nothing in any other environment. See the [development setup guide](https://gitmaster3000.github.io/agentira-oss-docs/contributing/development-setup).

### Multi-environment compose

Three explicit environments, **all three run simultaneously** on one host (distinct ports + isolated compose project names so they don't collide).

| Env | Frontend | Backend | MCP | DB | Hot reload | Compose project |
|---|---|---|---|---|---|---|
| **dev** | 3111 | 8111 | 8000 | Postgres | ✅ | `agentira` (default) |
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

Full walkthrough: [deployment guide](https://gitmaster3000.github.io/agentira-oss-docs/technical/deployment). The short version:

1. Provision Railway project + Postgres add-on.
2. Deploy three services from the same repo with different Dockerfiles: `Dockerfile` (backend), `Dockerfile.mcp` (mcp), and `frontend/Dockerfile` (frontend).
3. Wire `${{Postgres.DATABASE_URL}}` + `${{backend.JWT_SECRET}}` into MCP via Railway variable references.
4. Mount a 1GB Volume on backend `/app/data` so attachments survive redeploys.
5. Set `API_UPSTREAM` / `API_HOST` on the frontend service to your backend's address (they default to the compose `backend` service; `frontend/nginx.conf` substitutes them at startup).
6. Set `FRONTEND_URL` on the backend to your public frontend address — `agentira daemon login` needs it to build the browser approval link.

Migrations run automatically at startup (`scripts/bootstrap_db.py` → `init_db()`), idempotent on both SQLite and Postgres.

---

## Connecting AI agents (MCP)

Any MCP-aware client (Claude Desktop, Cursor, Antigravity, etc.) can talk to the workspace as either a user or an agent.

### HTTP / Bearer (recommended)

```json
{
  "mcpServers": {
    "agentira": {
      "serverUrl": "http://127.0.0.1:8000/mcp",
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
- **Attachments**: `create_attachment`, `read_attachment`, `delete_attachment` (task, project, or epic scoped)
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
│   ├── services.py                # core business logic
│   ├── attachments.py             # AP-152 attachments domain
│   ├── agent_templates.py         # AP-157 template loader
│   ├── gates.py                   # AP-158 transition gates
│   ├── sandbox.py                 # AP-155 sandbox resolver
│   ├── auth.py                    # RBAC + check_transition
│   ├── notifications.py           # ADR-007 broker
│   ├── jwt_auth.py
│   ├── db.py                      # engine + dialect-aware migrations
│   ├── models.py                  # core SQLAlchemy models
│   └── forge/                     # agent orchestration — self-contained
│       ├── router.py              # /api/forge/* routes
│       ├── services.py            # dispatch_trigger, complete_trigger, …
│       ├── models.py              # Agent, Run, AgentMessage, Conversation, …
│       ├── conductor.py           # orchestrator agent + queue tick
│       ├── ws_dispatch.py         # daemon WebSocket hub
│       ├── turns.py               # work-signal modes, crystallize
│       ├── live_inflight.py       # in-memory + on-disk inflight registry
│       └── mcp_registry.py        # MCP server registry + merge
├── agentira-cli/                  # CLI + daemon entry point (`agentira daemon`)
│   └── agentira_cli/runtimes/     # runtime adapters (claude, codex, grok, …)
├── templates/
│   ├── agents/                    # AP-157 default agent templates (yaml + md)
│   └── production-readiness.yaml  # project-workflow template (gate engine fodder)
├── scripts/
│   ├── bootstrap_db.py            # called at container start
│   └── ...
├── docs-oss/                      # documentation site (Docusaurus)
│   └── docs/
│       ├── user-guide/            # install, projects, agents, runs, gates
│       ├── technical/             # architecture, MCP, data model, ops
│       └── contributing/          # setup, conventions, testing, style
├── backend/tests/                 # backend test suite (ephemeral Postgres)
├── data/                          # volume-mounted: agentira.db (dev), attachments/
├── docker-compose.yml             # base — required env override
├── docker-compose.override.yml    # dev (auto-loaded)
├── docker-compose.qa.yml
├── docker-compose.prod.yml
├── Dockerfile                     # backend
├── Dockerfile.mcp                 # MCP server
├── railway.toml                   # Railway backend service config
├── frontend/                      # React/Vite UI (own package.json, Dockerfile, nginx.conf)
├── LICENSE                        # Apache-2.0
├── CONTRIBUTING.md                # how to get a task and get it merged
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
| Database | Postgres 16 everywhere — dev, qa, prod and the test harness |
| Tests | pytest · testcontainers-backed Postgres, never SQLite |
| MCP | `fastmcp` (HTTP + Stdio transports) |
| Frontend | React 18 · Vite 6 · TailwindCSS · React-Router · react-markdown |
| WebSocket dispatch | `websockets` library, per-daemon hub |
| Auth | JWT (stateless) + Google / GitHub OAuth + username/password |
| Daemon | Python `click` CLI, asyncio WS client, subprocess management |
| Default runtime | `claude` CLI (`@anthropic-ai/claude-code`) |
| Other runtimes | Codex CLI, Grok, OpenClaw (HTTP gateway), Ollama — the daemon detects whichever are on `PATH` |
| Deploy | Docker Compose · Railway · anything that runs Docker + Postgres |
| License | Apache-2.0 |

---

## Testing

Tests run against a real Postgres — `backend/tests/conftest.py` spins one ephemeral
`testcontainers` instance for the session and gives each test a fresh schema. **Docker
must be running.** Never SQLite: prod is Postgres, so the tests are too.

```bash
# Full backend suite — 735 passing as of the Apache-2.0 release commit
python -m pytest backend/tests/ -q

# One file while iterating
python -m pytest backend/tests/test_gates.py -q

# Frontend build
cd frontend && npm ci && npx vite build
```

`tests/` is the legacy root and folds into `backend/tests/` over time. The
`Integration test (full suite)` workflow runs both with the CLI installed — trigger it
by commenting `/integration-test` on a PR.

---

## Contributing

Start at [CONTRIBUTING.md](CONTRIBUTING.md). The short version: open a GitHub issue,
and if you want to take real work, ask for an account on the Agentira instance where
this project's own board lives — Agentira runs its own development, so contributors
work the same board the maintainers do.

The full code ruleset is in [CLAUDE.md](CLAUDE.md), but the short version:

- **Modular boundaries.** New domains get their own `backend/<domain>.py` (or `backend/forge/<domain>.py`). Functions over class hierarchies. Reach for OOP only when state or storage actually swaps.
- **Prompts-as-config.** Agent system prompts live on `Profile.system_prompt` (edited in Agent Settings UI). Task content lives on `Task.description` (edited in Task UI). No prompt text in dispatch code. No re-applying code constants on top of user-edited rows.
- **Surgical changes.** Touch only what the user's request needs. Don't refactor adjacent code. Match existing style.
- **Test what matters.** Every PR adds tests for the behavior it adds, regression-pins behavior it preserves.
- **CI must pass before merge.** Unit + integration smoke + compose-config validate are required.

---

## Project status

Working, self-hostable, and used to build itself — but early. Expect rough edges in
the places a two-person project has rough edges: the daemon installers are manual, sandbox
enforcement is config-only (Phase 2 is on the roadmap), and the docs lag the code in spots.

What is solid: the stack boots from a clean clone with `docker compose up`, the full
loop (board → task → dispatch → runtime → PR) works end to end, and nothing in a
self-hosted deployment depends on a service the maintainers control.

The canonical backlog is an Agentira board, not a GitHub Projects board — see
[CONTRIBUTING.md](CONTRIBUTING.md) for how to get access.

---

## License

[Apache-2.0](LICENSE). Permissive, with an explicit patent grant — you can run it,
fork it, and ship it inside a commercial product. See [NOTICE](NOTICE) for the
attribution notice.

---

## Acknowledgements

- The runs / turns / conversations model is shaped by the failure modes we hit dog-fooding Cursor and Claude Code on multi-day async work. ADR 009 is the post-mortem made architecture.
- The runtime adapter contract takes inspiration from how `claude --resume` and OpenClaw's `sessionKey` solve the same conversation-continuity problem from opposite directions.
- The MCP design follows the Model Context Protocol spec; thanks to the Anthropic + community work that makes "the agent's toolkit" a real abstraction.

---

<div align="center">

**Built for the moment you're not watching the screen.**

[Documentation](https://gitmaster3000.github.io/agentira-oss-docs/) · [Getting started](https://gitmaster3000.github.io/agentira-oss-docs/user-guide/first-project) · [Deployment](https://gitmaster3000.github.io/agentira-oss-docs/technical/deployment) · [Architecture](https://gitmaster3000.github.io/agentira-oss-docs/technical/architecture) · [Conventions](CLAUDE.md)

</div>
