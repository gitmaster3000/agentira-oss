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
