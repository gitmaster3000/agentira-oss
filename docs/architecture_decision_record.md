# ADR 009: Conversations, Turns & Runs — the Execution Backbone

## Status

Accepted (AP — "Conversations, Turns & Runs" epic)

## Context

We dogfood Agentira on its own development and kept hitting three failures that all
trace back to one under-specified piece of the architecture: the relationship between
a conversation, a dispatch, and a "run".

1. **`--resume` is unreliable.** claude keys `--resume <session_id>` by the **cwd** the
   session was created in. After a run finished or was cancelled, the daemon
   `git worktree remove`d that cwd (`_cleanup_worktree`, triggered by `cleanup_worktree`
   hints from `complete_trigger`). The next turn relaunched in a now-missing dir →
   "No conversation found with session ID". No-git projects never created the dir at
   all, and chats vs runs fell back to *different* scratch dirs (materializer `task_id="chat"`
   vs the real task id) — so a chat could never resume a run's session.
2. **Task chats ran as un-stoppable zombies.** A chat dispatch created **no Run row**, and
   its only liveness record was in-memory (`_TRACE_SCOPE` on the backend, `_inflight` on
   the daemon). A restart on either side orphaned it; `start_new_session=True` kept the
   claude process alive and unkillable. `scope_key` was never even sent on the trigger
   frame, so the daemon could neither serialize nor cancel by scope.
3. **No coherent model for "when is a conversation turn a run?"** — which produced endless
   thrash over whether a throwaway "hey" should create a run.

**Why runs exist at all.** Synchronous IDE assistants (Cursor, Claude Code, Antigravity)
have no concept of a "run" because a human watches every step live — the human *is* the
orchestrator, observer, and stop button. Agentira's value is the opposite: **autonomous
work while the human is absent.** The moment the human isn't watching, you need a durable
record that artifacts alone cannot provide: liveness (running/done/dead), a verdict
(succeeded/blocked/needs_input/failed), a stop/pause/resume handle, accounting (tokens,
cost, duration), trigger provenance (cron/webhook/manual), reconciliation when a daemon
dies, and an anchor for notifications. So we keep runs — but **demote** them from "the unit
you create per message" to "an emergent span over the turns that did work."

## Decisions

### 1. Three layered concepts (+ artifacts)

- **Conversation** — the agent's working memory for a scope; the claude `--resume` session.
  Belongs to the agent, continuous across everything in `(agent, scope_key)`. Stored in
  `forge_conversations`; the portable source of truth for replay is `forge_messages`.
- **Turn** — one dispatch (a user message + the agent's response, sharing one `trace_id`).
  **The atomic, always-durable, always-stoppable unit.**
- **Run** — an **emergent span grouping the turns of one work episode**, carrying the
  verdict, control surface, and accounting. Stored in `forge_runs`.
- **Artifact** — a concrete deliverable (pr/commit/file/url/log/report) on a run.

Some turns belong to a run (`run_id` set); some are standalone (`run_id` null) — and that
is fine.

### 2. Runs are demoted to emergent spans

A run is opened by the task **Run button**, or **lazily** when a standalone turn produces
work. A throwaway chat turn that produces nothing is just a turn — no run, no artifact.

### 3. Stable, never-destroyed conversation cwd

cwd is pinned per **(agent, task)** and is never torn down for the life of the task — it
*is* the conversation home, which is what makes `--resume` reliable. Git projects get a
per-(agent,task) worktree materialized once and reused; no-git projects use the directory
itself. The per-run worktree-teardown scheme (the un-ADR'd AP-123) is reverted; worktree
cleanup moves to a task archive/delete hook.

### 4. The DB is the portable source of truth

`forge_messages` is authoritative; `--resume` is a machine-local accelerator. When the
local session `.jsonl` is absent (fresh container, cloud daemon), history-replay
(`_prepend_history_for_prompt`) is a first-class fallback, not an error path. This is what
makes conversations portable to isolated/cloud daemons later. **Maximize `--resume`; replay
is the backup.**

### 5. One message-routing rule in a task scope

| Scope's run state | A new message does |
|---|---|
| no open run | start a standalone turn; lazily opens a run only if it produces work |
| RUNNING | interrupt-and-steer: pause the live turn, resume via `--resume` with the message — same `run_id` |
| PAUSED / NEEDS_INPUT / BLOCKED (parked) | resume the run via `--resume` |
| COMPLETED / FAILED / CANCELLED (terminal) | start a new turn that `--resume`s the conversation; new run only if it produces work |

The **Stop** button targets the live turn: if it belongs to a run, Stop = pause (resumable);
if standalone, terminate the turn.

### 6. Run detection never depends on `finish_run`

A standalone turn crystallizes into a run if **any** of: git work (per the work-signal
setting) **OR** `register_run_artifact` **OR** `finish_run`. `finish_run` is advisory and
non-blocking, so it can never be the sole gate. The **work-signal** is a project/run-default
setting — `working_tree` (default; committed + uncommitted tracked + new untracked,
excluding `.gitignore` and the materializer's `.agentira/*`), `tracked`, or `committed`.

### 7. Turns are durably stoppable across restarts

`scope_key` rides on the trigger frame; the daemon keeps an on-disk inflight registry keyed
by scope (written on spawn, cleared on completion); a startup orphan-reaper kills/re-adopts
survivors of a prior daemon; the heartbeat carries the live inflight set so the backend/UI
always know what's live (retiring the fragile in-memory `_TRACE_SCOPE`); the backend acks WS
registration so half-open sockets are detected; Stop is by scope, not a possibly-stale trace.

## Out of scope (intentional)

- Cross-machine *live* session handoff — replay covers correctness; deferred.
- Parallel worktrees for multiple concurrent runs *within one task* — runs serialize per
  (agent, task); cross-task concurrency is capped by `max_concurrent_runs`.
- Multi-repo per project (AP-121) — rebased onto the per-(agent,task) cwd as a fresh ticket.
- Per-run container isolation (AP-83 path B).

## Consequences

- `--resume` is reliable; zombie chats are gone; there is one durable handle (the turn);
  runs stay meaningful (work episodes), and chat is the primary ergonomic surface.
- `forge_runs` is no longer 1:1 with a dispatch — reporting/queries that assumed that must
  group by run across turns.
- `complete_trigger` gains a lazy-run-creation branch; the daemon gains an on-disk registry
  and a startup reaper.

## See also

ADR 008 (conversation scopes — this builds directly on `task:<task_id>` scoping), the
Stop/Pause/Resume P1–P4 reliability work, AP-130 (settings — hosts the work-signal selector).

---

# ADR 008: Conversation Scopes — Task-Based Memory, Universal `/clear`, Pause-on-Stop

## Status

Accepted (AP-93)

## Context

An "agent conversation" is the agent's working memory for a given context. Each
conversation has a `scope_key` and is identified per-agent (`forge_conversations`
keyed by `(agent_id, scope_key)`).

Before this ADR, three scope shapes existed:

- `chat:default` — one general chat per agent
- `chat:project:<pid>` — one chat per (agent, project)
- `run:<run_id>` — one conversation per individual task-run execution

The `run:<run_id>` shape created a serious UX failure: every time a user re-ran
the same task, the agent started a fresh conversation. It had no memory of what
worked or failed in earlier attempts. Users couldn't say "I tried that, it
didn't work — try X instead" because the agent had no record of the prior
attempt.

Separately, there was no way to:

- Clear an agent's memory in a scope when it had gone down a bad path.
- Stop an in-flight chat dispatch (different from canceling a run).
- Pause and resume a long-running task naturally.

## Decisions

### 1. Task-scoped conversations (`task:<task_id>`)

Replace `run:<run_id>` with `task:<task_id>` as the scope key for any
dispatch tied to a task. All runs of the same task by the same agent share
**one** conversation. Each Run row still exists as a distinct execution
(diff, tokens, outcome, status, branch) — only the agent's working memory
is now cumulative.

`conversation_scope_key()` precedence:

```
if task_id:      → "task:<task_id>"
elif project_id: → "chat:project:<project_id>"
else:            → "chat:default"
```

`run_id` no longer drives scope.

### 2. `/clear` is the universal "wipe this conversation" verb

A slash command in the chat input. Works for every scope (`chat:default`,
`chat:project:*`, `task:*`). Effects:

- Drops `forge_conversations.runtime_session_id` for the current scope.
- Drops `forge_messages` rows for that scope.
- Confirmation prompt before execution (destructive).
- Does NOT touch Run rows, diffs, summaries, or task comments.

### 3. Stop button in chat = cancel + pause when run-bound

When the agent is mid-dispatch in a chat:

- **Cancel** the in-flight subprocess (graceful).
- If the active scope is `task:<id>` AND there's a `Run` in `RUNNING`
  status for that task → also mark `Run.status = PAUSED`.
- Session id is preserved (resumable via `claude --resume <id>`).

### 4. Sending a message into a paused-run scope auto-resumes

When user sends a new message in a scope whose task has `Run.status =
PAUSED`:

- Mark `Run.status = RUNNING` again.
- Fresh dispatch with `claude --resume <session_id>` so claude has full
  prior context.
- New message is the next user turn from claude's POV.
- UI surfaces a "resumed paused run" badge so the user knows.

### 5. Dedicated Pause / Resume on Run detail

Same primitives, surfaced as explicit buttons on the Run detail page for
direct control without going through the chat input. Resume button
dispatches with a `Continue your work.` preamble (no new user content
needed).

### 6. Migration: backfill `best-coder` only

A one-shot script retags `run:<run_id>` → `task:<task_id>` for `best-coder`'s
existing conversations and messages. Other agents' historical
conversations stay as `run:<run_id>` and remain readable but discontinuous
from new task-scoped chats. Scoped to one agent because (a) avoids risk on
production data and (b) `best-coder` is where the user actually wants
historical continuity.

## Out of scope (intentional)

- **Multiple chat threads per (agent, project)**. Future addition if users
  ask. Scheme reserved: `chat:project:<pid>:thread:<tid>`.
- **Cross-project unified chat**. Stays per-project; cross-project context
  goes via the `+` attach-as-reference button.
- **@mention dispatch wiring**. Tracked as AP-96. Will use the same
  `task:<task_id>` scope when it lands.
- **Cross-machine resume**. Tracked as AP-94.

## Consequences

Positive:

- Agent has continuous memory across re-runs of the same task.
- Universal `/clear` gives users a predictable escape hatch.
- Pause/resume becomes natural (just send a message).
- Each agent retains independent memory for the same task — no cross-agent
  leakage.

Negative:

- One-time discontinuity for non-`best-coder` agents on existing runs:
  their old `run:<run_id>` conversations stop accumulating; new runs
  start fresh task-scoped. Acceptable trade-off given low data volume
  in those scopes.
- Run row's `status` field becomes more nuanced (PAUSED added as a real
  user-driven state, distinct from PENDING/RUNNING/COMPLETED/FAILED/
  CANCELLED). UI must surface PAUSED clearly.

## See also

- AP-93 (this ADR)
- AP-95 (`/clear` slash command — folded into AP-93's scope)
- AP-96 (@mention dispatch — uses this scope scheme)
- `docs/conversations.md` (user-facing guide)

---

# ADR 007: Push-Based Agent Notification via Webhook Receiver + Notification Poll Fallback

## Status

Accepted

## Context

Agentira agents (ZeroClaw daemons and any other process-based agent) need to react to
platform activity — task moves, comments, new assignments, project changes — without a
human manually prompting them. The previous approach relied on each agent's ZeroClaw
cron job polling `list_tasks` every N minutes. This has two problems:

1. **Latency**: events are visible to the agent up to N minutes after they occur.
2. **Waste**: every poll cycle hammers the API regardless of whether anything has changed.

The mechanism must satisfy hard constraints:

- Must NOT couple to any specific agent framework (ZeroClaw, OpenClaw, LangChain, etc.)
- Must NOT use SSE (product decision — SSE implies a persistent connection owned by the
  backend, which complicates horizontal scaling and agent lifecycle management)
- Must work with any agent that can bind to a port and parse JSON
- Must degrade gracefully to pure polling when the agent cannot accept inbound connections
  (NAT, firewall, IDE wake/sleep agents — out of scope for this sprint but must not break)

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| Cron job on agent side (existing) | Already works, zero new code | Slow (minutes), agent owns scheduling complexity |
| Enhanced polling loop in daemon | No new infra, resilient | Still slow; every cycle makes API calls regardless |
| SSE stream (backend pushes) | Instant, one connection | Ruled out; persistent connection; scaling issues |
| Webhook push only (backend → agent) | Instant, fully decoupled | Delivery not guaranteed |
| **Hybrid: webhook push + notification poll fallback** | Instant _and_ resilient; no framework coupling | Slightly more complex daemon |

## Architecture

Agents are long-running HTTP servers. The Agentira backend calls them (via webhook POST)
when relevant events occur. This is the intended model — agents are not passive clients,
they are addressable processes that the backend can reach.

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  AGENTIRA BACKEND                                                            ║
║                                                                              ║
║  ┌──────────────────┐   event   ┌────────────────────┐                      ║
║  │  services.py     │ ────────► │  agent_notifier.py │                      ║
║  │                  │           │                    │                      ║
║  │  task.assigned   │           │  Consults webhook  │                      ║
║  │  task.moved      │           │  config to decide: │                      ║
║  │  task.commented  │           │  - which events    │                      ║
║  │  task.created    │           │    to dispatch     │                      ║
║  │  task.updated    │           │  - which receivers │                      ║
║  │  project.updated │           │    (bots / all /   │                      ║
║  │                  │           │     custom list)   │                      ║
║  └──────────────────┘           └────────┬───────────┘                      ║
║                                          │  POST /webhook                   ║
║  ┌───────────────────────────────────┐   │  (one request per target bot)    ║
║  │  Notification DB                  │   │                                  ║
║  │  (existing)                       │   │                                  ║
║  │  Notification row written         │   │                                  ║
║  │  for each relevant profile        │   │                                  ║
║  └───────────────────────────────────┘   │                                  ║
║                                          │                                  ║
║  ┌───────────────────────────────────┐   │                                  ║
║  │  REST API                         │◄──┼── poll fallback (Path B)         ║
║  │  GET /api/notifications           │   │   GET /api/notifications         ║
║  │      ?actor=bot&unread_only=true  │   │   (existing endpoint, reused)    ║
║  │  PATCH /api/notifications/:id/read│   │                                  ║
║  │                                   │   │                                  ║
║  │  MCP tools (also available):      │   │                                  ║
║  │  agentira__get_notifications      │   │                                  ║
║  │  agentira__mark_notification_read │   │                                  ║
║  └───────────────────────────────────┘   │                                  ║
╚══════════════════════════════════════════╪═══════════════════════════════════╝
                                           │
                         Path A (push)     │     Path B (poll fallback)
                                           │
╔══════════════════════════════════════════╪═══════════════════════════════════╗
║  AGENT DAEMON (long-running HTTP server) │                                  ║
║                                          │                                  ║
║  ┌──────────────────────────────┐        │                                  ║
║  │  WebhookReceiver             │◄───────┘                                  ║
║  │  stdlib http.server          │  POST /webhook (Path A)                   ║
║  │  port: 9111 (configurable)   │                                           ║
║  │                              │                                           ║
║  │  1. Validate X-Agentira-Token│                                           ║
║  │  2. Parse structured payload │                                           ║
║  │  3. queue.put(event)         │                                           ║
║  │  4. wake_event.set() ────────┼──────────────────────────┐                ║
║  └──────────────────────────────┘                          │                ║
║                                                            ▼                ║
║  ┌──────────────────────────────────────────────────────────────────────┐   ║
║  │  AgentiraDaemon — main loop                                          │   ║
║  │                                                                      │   ║
║  │  wake_event.wait(timeout=poll_interval)                              │   ║
║  │       │                                                              │   ║
║  │       ▼  (woken by webhook OR interval timeout)                      │   ║
║  │                                                                      │   ║
║  │  [Path A] drain event queue — log structured event context           │   ║
║  │                                                                      │   ║
║  │  [Path B] GET /api/notifications?unread_only=true                    │   ║
║  │           process each unread notification                           │   ║
║  │           PATCH /api/notifications/:id/read (mark consumed)          │   ║
║  │                                                                      │   ║
║  │  poll_and_execute()                                                  │   ║
║  │  ├── list tasks in_progress → resume highest priority                │   ║
║  │  ├── list tasks todo        → move to in_progress, execute           │   ║
║  │  └── list tasks backlog     → fallback                               │   ║
║  └──────────────────────────────────────────────────────────────────────┘   ║
╚══════════════════════════════════════════════════════════════════════════════╝

ZeroClaw agents (MCP-based, no embedded daemon):
  Poll fallback uses existing MCP tool: agentira__get_notifications
  No webhook receiver needed — ZeroClaw's own cron handles the poll cycle
```

## Decision

Adopt a **hybrid push + notification poll fallback** architecture:

### Primary — Path A: Outbound Webhook Push (instant)

The backend fires `POST <profile.webhook_url>` when relevant events occur. Which events
fire and who receives them is controlled by a **webhook configuration** (see below) —
not hardcoded. The default targets bots only.

The daemon embeds a zero-dependency stdlib HTTP server (`WebhookReceiver`) that:
- Listens on a configurable port (default: 9111)
- Validates an optional `X-Agentira-Token` shared secret on every request
- Parses the structured payload and places it on a `queue.Queue`
- Calls `threading.Event.set()` to interrupt the daemon's poll sleep immediately

The daemon's main loop replaces `time.sleep` with `threading.Event.wait(timeout=N)`,
giving sub-second reaction time on push.

### Fallback — Path B: Notification Poll (resilient)

On every wake cycle the daemon calls `GET /api/notifications?actor=bot&unread_only=true`
using the **existing** notification endpoint and marks each processed notification as
read via `PATCH /api/notifications/:id/read`.

This reuses the existing notification system without any new backend endpoint. It catches
any events missed due to webhook delivery failure, daemon restart, or misconfiguration.
It is the authoritative recovery path; webhooks are an optimisation.

MCP-based agents (ZeroClaw) use the equivalent existing MCP tool
`agentira__get_notifications` on their own cron cycle — no daemon changes needed for
those agents.

### Graceful Degradation

Setting `notification_mode: poll` in the YAML config disables the webhook receiver
entirely. The daemon reverts to notification polling only, with no other changes.

## Webhook Configuration

**Subscription rules are backend-owned, stored per project in the DB** as a JSON column
(`Project.webhook_config`). This is the source of truth — not the daemon's local config.
The backend controls which events fire to which receiver groups. This was a deliberate
choice to avoid technical debt: a separate `webhook_rules` table is premature, but the
JSON schema is designed so migrating to a table later is mechanical.

```json
{
  "enabled": true,
  "rules": [
    { "event": "task.assigned",      "receivers": "assignee" },
    { "event": "task.moved",         "receivers": "assignee" },
    { "event": "task.commented",     "receivers": "assignee" },
    { "event": "task.created",       "receivers": "bots"     },
    { "event": "task.updated",       "receivers": "assignee" },
    { "event": "project.updated",    "receivers": "bots"     },
    { "event": "project.member.add", "receivers": "assignee" }
  ]
}
```

If `Project.webhook_config` is `null`, the dispatch layer applies `DEFAULT_WEBHOOK_RULES`
(a constant in `agent_notifier.py`). Existing projects get sensible defaults without a
migration.

**Receiver groups:** `assignee` (task's current assignee), `bots` (all bot-role project
members), `members` (all project members). Expanding receiver groups or adding conditions
is a JSON schema change, not a DB migration.

**Validation:** `WebhookRule` and `ProjectWebhookConfig` Pydantic models validate the
JSON at the service layer before persistence and before dispatch.

The **daemon YAML** only carries receiver-side config — not subscription rules:

```yaml
# agents/config.yaml

connection:
  api_url: http://127.0.0.1:8111
  api_key: "your-bot-api-key"
  bot_name: arch-bot

polling:
  interval: 120       # seconds between poll cycles
  mode: hybrid        # hybrid | webhook | poll

webhook:
  port: 9111          # 0 = disabled
  token: ""           # shared secret; empty = no auth (safe for localhost)

execution:
  max_agent_turns: 20
  dry_run: false
  zeroclaw_port: 42617

logging:
  level: INFO
```

## Payload Contract — Structured Only

The webhook payload carries **structured fields only**. There is no pre-composed
`message` string — that would be a prompt injection vector, since task titles and
comments are user-supplied content that must never be passed raw to an LLM.

The daemon constructs its own sanitised context from the structured fields when
building prompts.

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

For project-level events (`project.updated`, `project.member.add`), `task_id` is omitted
and `project_id` is the primary identifier.

## Implementation Surface

| File | Change | Notes |
|---|---|---|
| `backend/models.py` | MODIFY | add `webhook_config` JSON col to `Project`; add `notification_transport` enum col to `Profile` |
| `backend/services.py` | MODIFY | `WebhookRule` + `ProjectWebhookConfig` Pydantic models; `get_webhook_targets()`; `resolve_transport()`; `DEFAULT_WEBHOOK_RULES`; expanded event firing |
| `backend/agent_notifier.py` | MODIFY | remove `message` field; add `notify_many()`; project-level payload builder; config-driven dispatch |
| `backend/rest_api.py` | MODIFY | add `GET/PUT /api/projects/:id/webhook-config` endpoints |
| `agents/webhook_receiver.py` | NEW | stdlib HTTP server, zero external deps |
| `agents/daemon.py` | MODIFY | interrupt-aware sleep; receiver startup; notification poll fallback |
| `agents/config.py` | REPLACE with `agents/config.yaml` | YAML-based; receiver-side config only (rules stay in backend DB) |
| `agents/agentira_client.py` | no change needed | existing `get_notifications` / `mark_notification_read` cover the poll fallback |
| `docs/setup-agent-guide.md` | UPDATE | webhook setup section |
| `docs/continuous-execution-architecture.md` | NEW | full architecture reference with Mermaid diagrams |

## Event Coverage After Implementation

| Event | Webhook (default receivers) | Notification fallback |
|---|---|---|
| `task.assigned` | assignee only | yes |
| `task.moved` | assignee only | yes |
| `task.commented` | assignee only | yes |
| `task.created` | all project bots | yes |
| `task.updated` (metadata) | assignee only | yes |
| `project.updated` | all project bots | yes |
| `project.member.add` | added member only | yes |

Receiver groups are configurable per-event via the YAML subscription rules.

## Consequences

**Positive**
- Agent reaction time drops from minutes to sub-second for push-enabled deployments
- No new runtime dependency — stdlib `http.server` only
- Any agent that can bind a port and parse JSON qualifies — no framework coupling
- Poll fallback reuses the existing notification system with zero new backend endpoints
- MCP-based agents get fallback for free via existing `agentira__get_notifications` tool
- Payload is structured only — no prompt injection surface in the webhook path
- Webhook subscription rules are configurable per-event and per-receiver group

**Trade-offs**
- Agents run as HTTP servers (this is the intended model: agents are addressable
  processes the backend calls; it is not a constraint, it is the design)
- IDE-based agents (Claude Code, Cursor) with a wake/sleep cycle tied to user prompts
  are not addressable as servers — this use case requires a separate mechanism and is
  explicitly out of scope for this sprint
- Subscription rule enforcement at the backend level (project-wide defaults) ships first;
  per-agent custom rules via YAML require a future config-sync endpoint

## Related

- ADR-005: Service Accounts for Agent Identity
- ADR-006: ZeroClaw WebSocket Proxy for Dashboard Chat

---

# ADR 006: ZeroClaw WebSocket Proxy for Dashboard Chat

## Context

ZeroClaw agents expose a web dashboard at their gateway port (e.g. `localhost:3011`) which includes an agent chat UI. The chat UI uses a WebSocket connection to `ws://localhost:<port>/ws/chat`.

Browsers enforce a strict rule from the WebSocket spec (RFC 6455): if the client sends a `Sec-WebSocket-Protocol` header in the upgrade request, the server **must** echo back one of the requested subprotocols in its `101 Switching Protocols` response. If the server omits this header, the browser aborts the connection.

ZeroClaw's frontend JavaScript always sends `Sec-WebSocket-Protocol: bearer.<token>` to pass the authentication token (browsers cannot send custom `Authorization` headers on WebSocket connections). ZeroClaw v0.1.8's gateway accepts the token and authenticates correctly, but **does not echo the subprotocol back** in the `101` response. This is a bug in ZeroClaw.

Result: the WebSocket handshake always fails in the browser, making the dashboard chat permanently unusable, even though the underlying agent works correctly (confirmed via CLI and curl).

## Decision

Run a lightweight Python TCP proxy (`ws_proxy.py`) that sits in front of ZeroClaw and patches the WebSocket handshake:

- Proxy listens on the original ZeroClaw port (`3011`)
- ZeroClaw is moved to an offset port (`3015`)
- On every WebSocket upgrade, the proxy reads the `Sec-WebSocket-Protocol` value from the request, forwards the request to ZeroClaw, and injects the missing `Sec-WebSocket-Protocol` header into ZeroClaw's `101` response before forwarding it to the browser
- If ZeroClaw already echoes the header (future fix), the proxy skips injection to avoid duplicates
- All other traffic (HTTP, non-WebSocket) is tunnelled transparently

The proxy is started as a background process alongside the ZeroClaw daemon.

## Consequences

- Dashboard agent chat works correctly in the browser
- No changes to ZeroClaw binary or config (beyond port offset)
- When ZeroClaw fixes the bug upstream, `ws_proxy.py` can be removed and ZeroClaw moved back to `3011`
- Each agent that needs a working dashboard requires its own proxy instance on its original port

## Ports

| Component | Port |
|---|---|
| Proxy (architect) | 3011 |
| ZeroClaw architect | 3015 |

## Files

- `C:\agentira\ws_proxy.py` — the proxy implementation

---

# ADR 005: Service Accounts for Agent Identity

## Context
We need to support AI agents interacting with the system.
- Agents need stable credentials (API Keys).
- Agents need to be distinguishable from human users.
- Agents need to be able to set their own "personality" (name/avatar).
- Humans need control over agent access (provisioning/revocation).

## Decision
We implement a **Service Account** model with **Agent Self-Configuration**.

### 1. Service Accounts (Bots)
- **Definition**: A `Profile` with `role="bot"`.
- **Creation**: Explicitly created by a human via `POST /api/service-accounts`.
- **Credential**: An `api_key` is generated at creation time and returned to the human.
- **Management**: Humans can list and revoke (delete) these accounts via Settings.

### 2. Agent Autonomy
- **Authentication**: Agents use the provided `api_key` to authenticate via MCP.
- **Self-Configuration**: Agents can call `update_profile` tool to set their own `display_name` and `avatar_url`. This allows a generic "Bot" to become "Code Assistant" upon first run.

### 3. Separation of Concerns
- **Identity Provisioning**: Handled by Humans (Security).
- **Identity Configuration**: Handled by Agents (Personality).
- **No Open Signup**: The `signup` tool is removed from MCP to prevent unauthorized account creation.

## Consequences
- **Pros**:
    - Secure: No open signup.
    - Controllable: Humans own the keys.
    - Flexible: Agents can still have unique identities.
- **Cons**:
    - Manual step: Humans must generate a key before an agent can run. (This is a desired feature for security).

## Verification
- `tests/test_agent_identity.py` validates the entire lifecycle.
