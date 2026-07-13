# Agentira Self-Build Handover

How to hand the Agentira build off to an 8-agent fleet that continues
developing the platform itself.

## Prerequisites

All of these PRs must be merged to `main`:

| PR | What it unlocks |
|---|---|
| #32 | Conductor — autonomous todo-task pickup |
| #33 | Project digest — overnight visibility |
| #35 | agentira-project MCP — agents can read the repo |
| #37 | OpenClaw MCP wiring — Qwen/Kimi agents get tools |
| #36 | Daemon reliability — supervised, won't silently die |
| #31 | Rebuild-history — agents keep memory without native resume |

Plus a working daemon host with **Claude** and **OpenClaw** runtimes.

## The fleet

`scripts/bootstrap_agents.py` creates 8 agents:

| Agent | Runtime | Role | Conductor |
|---|---|---|---|
| planner | Claude | Breaks goals into scoped tasks | off |
| reviewer | Claude | Reviews diffs, gates review→done | off |
| implementer-1 | Claude | Implements todo tasks | **on** |
| implementer-2 | Claude | Implements todo tasks | **on** |
| implementer-qwen-1 | OpenClaw/Qwen | Implements todo tasks | **on** |
| implementer-qwen-2 | OpenClaw/Qwen | Implements todo tasks | **on** |
| implementer-kimi-1 | OpenClaw/Kimi | Implements todo tasks | **on** |
| test-writer-kimi | OpenClaw/Kimi | Adds test coverage | **on** |

Planner and Reviewer stay manual — you decide what work enters the board
and the Reviewer is dispatched on review-column tasks, not todo pickup.

## Handover steps

### 1. Start the daemon

```bash
agentira daemon start
agentira daemon status          # confirm: running + WebSocket connected
```

This registers Claude + OpenClaw runtimes and idempotently adds the
per-Agentira engine agents (`ar-<id>`) in OpenClaw (see openclaw-engine-agents.md).

### 2. Seed OpenClaw MCP servers

```bash
agentira daemon install-openclaw-mcps \
    --api-key <BOT_API_KEY> \
    --repo-path /path/to/agentira
```

One-time seed. At runtime the daemon overwrites these per-dispatch with
each agent's own token + memory path (AP-103), so identity stays
per-agent.

### 3. Bootstrap the fleet

```bash
python scripts/bootstrap_agents.py \
    --api-url http://localhost:8111 \
    --api-key <ADMIN_API_KEY> \
    --project-id <AGENTIRA_PROJECT_ID> \
    --enable-conductor
```

Idempotent on agent name — safe to re-run.

### 4. Feed the board

The Planner agent (or you) creates `todo` tasks. The Conductor tick
(~60s) dispatches each todo task to an idle conductor-enabled agent.

### 5. Check the digest

```
GET /api/forge/projects/<project-id>/digest?since=24h
```

Shows what the fleet did: done / blocked / failed / in-flight, cost,
tokens. Wire it into ForgeOverview for a dashboard card.

## The loop, once handed over

```
Planner → creates todo tasks
   ↓
Conductor → dispatches todo → idle implementer agent
   ↓
Implementer → works, opens PR-shaped change, finish_run
   ↓
Reviewer → checks evidence, moves review → done (or rejects)
   ↓
Digest → you read it the next morning
```

## What still needs a human

- Merging PRs (no auto-merge — by design)
- The Planner's task list — what to build next
- Reviewer dispatch on review-column tasks
- Anything an agent marks `blocked`

## Known limits at handover

- OpenClaw agents share one workspace (AP-103 Step 2 not done) — for
  true file-level isolation, one daemon per OpenClaw agent, or keep
  OpenClaw agents on non-overlapping tasks.
- No verified state machine (AP-81) — an agent can claim done without a
  merged PR. The Reviewer is the human-trust substitute until AP-81.
- Conductor is FIFO, no priority ordering (AP-80 v1).
