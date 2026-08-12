---
id: architecture
title: Architecture
sidebar_label: Architecture
---

# Architecture

Agentira splits into four layers. The split is not arbitrary: the code being edited lives on a developer's machine, so execution has to happen there, while coordination benefits from being central.

```
┌──────────────────────────────────────────────┐
│  Browser (React 18, Vite)                    │
│  Board, tasks, agents, runs                  │
└──────────────────┬───────────────────────────┘
                   │ HTTPS / WebSocket
                   ▼
┌──────────────────────────────────────────────┐
│  Backend (FastAPI, Postgres)                 │
│  • REST API           — for people           │
│  • MCP server         — for agents           │
│  • Conversations / turns / runs              │
│  • Gate engine, evidence providers           │
│  • Sandbox resolver, dispatch outbox         │
└──────────────────┬───────────────────────────┘
                   │ WebSocket (dispatch frames)
                   ▼
┌──────────────────────────────────────────────┐
│  Daemon (on the user's machine)              │
│  • Receives dispatch                         │
│  • Owns Git worktrees and logs               │
│  • Starts the runtime, streams events back   │
└──────────────────┬───────────────────────────┘
                   │ subprocess
                   ▼
┌──────────────────────────────────────────────┐
│  Runtime (Claude CLI, Codex, Grok, Ollama…)  │
│  Edits files. Commits. Opens pull requests.  │
└──────────────────────────────────────────────┘
```

The backend coordinates. The machine executes. Nothing in a self-hosted deployment depends on a maintainer-controlled service.

## Backend

FastAPI over SQLAlchemy 2 and Postgres. Two entry surfaces share one services layer:

| Surface | Consumers | Auth |
|---|---|---|
| REST API (`/api/*`) | Browser, CLI | JWT, or API key |
| MCP server | Agents, external MCP clients | Bearer API key |

Both paths run the same permission checks. There is no weaker path for agents.

### Module layout

```
backend/
├── rest_api.py          # router mounting
├── mcp_server.py        # MCP tool definitions
├── services.py          # core business logic
├── models.py            # SQLAlchemy models
├── db.py                # engine, dialect-aware migrations
├── auth.py              # RBAC, transition checks
├── jwt_auth.py
├── gates.py             # transition gates
├── sandbox.py           # sandbox resolver
├── attachments.py
├── task_graph.py        # dependencies
├── notifications.py
├── agent_templates.py
├── repo_tokens.py
├── deploy/              # deployment adapters
└── forge/               # agent orchestration, self-contained
    ├── router.py            # /api/forge/*
    ├── services.py          # dispatch and completion
    ├── models.py            # Agent, Run, Conversation, AgentMessage
    ├── conductor.py         # orchestrator, queue tick, planning
    ├── ws_dispatch.py       # daemon WebSocket hub
    ├── dispatch_outbox.py   # at-least-once delivery
    ├── turns.py             # work signals, crystallisation
    ├── runs.py, run_state.py
    ├── evidence.py          # evidence providers
    ├── workflow.py          # workflow definitions
    ├── live_inflight.py     # restart-proof in-flight registry
    ├── reconciler.py        # stale-run sweep
    ├── scheduler.py
    ├── compaction.py, context.py, digest.py
    ├── epic_planning.py
    ├── mcp_registry.py
    └── model_catalog.py
```

`backend/forge/` is self-contained. It uses real foreign keys to the rest of the schema rather than string references, but its logic does not leak outward.

New domains get their own module. They are not appended to `services.py`.

### Data access

Services compose; repositories own the SQL. Orchestration modules do not issue queries inline. Each domain has repository functions that encapsulate transactions, eager loading, and dialect differences.

Some legacy code still queries directly. New code uses repositories, and touched legacy queries are migrated as they are touched.

## Daemon

A Python CLI (`agentira-cli/`) that runs on the user's machine.

Responsibilities:

1. Authenticate to the backend and hold a WebSocket connection.
2. Detect available runtimes and report their capabilities.
3. Receive dispatch frames.
4. Provision a Git worktree for the agent and task.
5. Start the runtime as a subprocess with the right environment.
6. Stream events back.
7. Enforce the concurrency cap.
8. Reap orphaned processes at startup.

### Filesystem layout

```
~/.agentira/
├── credentials.json
├── agents/<agent>/home/repos/<project>/task-<id>/   # stable working directory
├── runs/<run-id>/{stdout.log,stderr.log,meta.json}
└── inflight/<scope>.json                            # survives restarts
```

The working directory per agent and task is stable, which is what lets a runtime resume its prior session. The worktree inside is recreated per run.

:::note Known limitation
`AGENTIRA_HOME` does not currently isolate agent workspaces. The backend passes the daemon a literal home path, so a second daemon intended to be isolated still writes to the real home.
:::

## Runtime layer

The runtime is the external tool that edits code. Adapters live in `agentira-cli/agentira_cli/runtimes/` and map Agentira's contract onto each tool's native features.

See [Runtimes](./runtimes.md).

## Dispatch reliability

Dispatch is at-least-once, not fire-and-forget:

- **Outbox.** Dispatch frames are persisted before sending and redelivered if unacknowledged.
- **Heartbeats.** The WebSocket hub tracks liveness with configurable intervals and timeouts.
- **In-flight registry.** In-flight turns are recorded in memory and on disk, so a backend or daemon restart does not lose them.
- **Reconciler.** A periodic sweep marks runs whose daemon vanished.
- **Automatic retry.** A subprocess crash mid-run resumes the session.

## Frontend

React 18, Vite 6, TailwindCSS, React Router. Built to a static bundle and served by nginx, which proxies the API using addresses substituted at container start.

## Design rules

Four rules shape the codebase. They are enforced in review.

**Prompts are configuration, not code.** Agent system prompts live on the profile row and task content on the task row, both edited in the interface. No prompt text is hardcoded in dispatch code, and code constants are never re-applied over a user-edited row. Seeding sets a field only when empty.

**Autonomy is transparent or it does not ship.** Any mechanism deciding task movement must be declared in configuration, evaluated through the gate engine, recorded with an evidence snapshot, and visible in the interface. No hidden heuristics, no string-matching on comments, no inferring intent from history.

**Plain language by default.** Everything user-facing stays in plain language. Technical internals go behind an optional Advanced reveal. A non-engineer must see the same honest status an engineer does.

**Postgres everywhere.** Development, QA, production, and the test harness all run Postgres. Tests never use SQLite, because production does not.
