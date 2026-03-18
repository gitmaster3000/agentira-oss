# Continuous Execution Architecture

Describes the push-based agent notification system that enables always-on daemon agents
(ZeroClaw, OpenClaw, custom) and wake-on-demand agents (VS Code Copilot, Antigravity)
to react to Agentira platform events in real time.

See [ADR-007](./architecture_decision_record.md) for the full decision record.

---

## 1. System Overview

```mermaid
flowchart TD
    Human(["Human · Agentira UI :3111"])

    subgraph Backend["Agentira Backend · K8s stateless pods"]
        SVC["services.py\nevent processing"]
        NOTIFIER["agent_notifier.py\ndispatch layer"]
        REST["REST API :8111"]
        MCP["MCP Server :8000"]

        subgraph DB["Shared Database  (Postgres prod · SQLite dev)"]
            NOTIF_TBL[("Notification rows\nsource of truth")]
            WH_CFG[("Project.webhook_config\nJSON column · per-project rules")]
            PROF_TRN[("Profile.notification_transport\nenum: webhook · sse · poll")]
        end
    end

    subgraph CatA["Category A · Always-on Daemon Agents"]
        subgraph Daemon["Agentira Python Daemon"]
            WH_RECV["WebhookReceiver\nPOST /webhook :9111\ntoken · queue · wake"]
            LOOP["Main Loop\nwake_event.wait(timeout)"]
            EXEC["Executor  pluggable\nZeroClaw · OpenClaw · LLM · subprocess"]
        end
        OC["OpenClaw\nnative webhook endpoint"]
    end

    subgraph CatB["Category B · Wake-on-demand Agents"]
        VSCODE["VS Code Copilot · Antigravity IDE\npoll on wake via MCP tool"]
        SSE_P2["SSE Session  Phase 2\noutbound stream · reconnect · poll fallback"]
    end

    Human -->|REST| SVC
    SVC -->|"1 · write"| NOTIF_TBL
    SVC -->|"2 · dispatch"| NOTIFIER
    NOTIFIER -->|reads rules| WH_CFG
    NOTIFIER -->|reads transport| PROF_TRN
    NOTIFIER -->|"webhook POST"| WH_RECV
    NOTIFIER -->|"webhook POST"| OC
    REST ---|query| NOTIF_TBL
    MCP ---|query| NOTIF_TBL
    WH_RECV --> LOOP
    LOOP --> EXEC
    LOOP -->|"poll fallback\nGET /api/notifications"| REST
    VSCODE -->|"agentira__get_notifications"| MCP
```

---

## 2. Notification Dispatch Flow

```mermaid
flowchart TD
    EVT["Event occurs\ncreate · move · comment · update · project change"]
    WRITE["1. Write Notification to DB\nsource of truth · always first"]
    DISPATCH["2. agent_notifier.dispatch(event, payload, actor)"]
    RULES["Read project.webhook_config\nfalls back to DEFAULT_WEBHOOK_RULES if null"]
    RESOLVE["For each target profile:\nresolve_transport(profile)"]

    WH["transport = webhook\nPOST profile.webhook_url\nX-Agentira-Token header\nbackground thread · fire and forget"]
    SSE["transport = sse  Phase 2\npublish to Redis/NATS channel\nstream to connected SSE clients"]
    POLL["transport = poll\nno-op here\nagent pulls GET /api/notifications\non its own schedule"]

    EVT --> WRITE
    WRITE --> DISPATCH
    DISPATCH --> RULES
    RULES --> RESOLVE
    RESOLVE --> WH
    RESOLVE --> SSE
    RESOLVE --> POLL
```

---

## 3. Webhook Delivery Sequence

```mermaid
sequenceDiagram
    actor Human
    participant API as Agentira API
    participant DB as Database
    participant AN as agent_notifier
    participant WR as WebhookReceiver :9111
    participant DL as Daemon Main Loop

    Human->>API: POST /api/tasks/:id/move  status=review
    API->>DB: INSERT Notification row  (durable)
    API->>AN: dispatch(task.moved, task, actor)
    AN->>DB: SELECT project.webhook_config
    AN->>DB: SELECT target profiles by receiver_group
    AN-->>WR: POST /webhook  (background thread)
    Note over AN,WR: header: X-Agentira-Token: secret
    API-->>Human: 200 OK  webhook fires async

    WR->>WR: validate token
    WR->>WR: parse structured JSON payload
    WR->>WR: queue.put(event)
    WR->>DL: wake_event.set()

    DL->>DL: wake from wait()  drain queue
    DL->>API: GET /api/notifications?unread_only=true
    API->>DB: SELECT unread notification rows
    DB-->>API: rows
    API-->>DL: notification list
    DL->>API: PATCH /notifications/:id/read
    DL->>DL: poll_and_execute()
    DL->>DL: run task via executor
```

---

## 4. Kubernetes Topology

```mermaid
flowchart LR
    subgraph K8S["Kubernetes Cluster"]
        subgraph BackendSvc["backend Service  ClusterIP  :8111"]
            P1["Pod 1\nhandles write request\nfires webhook inline"]
            P2["Pod 2\nserves poll requests"]
            P3["Pod 3\nserves poll requests"]
        end

        PG[("Postgres\nShared DB")]

        subgraph AgentSvcs["Agent Services  ClusterIP"]
            ARCH_SVC["arch-bot-svc :9111\nWebhookReceiver"]
            OC_SVC["openclaw-bot-svc :PORT\nOpenClaw native handler"]
        end
    end

    P1 -->|write| PG
    P1 -->|"POST webhook\none pod · no duplication"| ARCH_SVC
    P1 -->|POST webhook| OC_SVC
    P2 -->|serve poll| PG
    P3 -->|serve poll| PG
```

> **Why webhooks work in K8s without a broker:** each API request is handled by exactly
> one pod. That pod writes the notification and fires the webhook inline — one fire, no
> duplication. The notification row is the durable fallback; any pod can serve the poll.
>
> **Why SSE needs a broker in K8s:** SSE connections live on one pod. An event on Pod 2
> cannot reach a client connected to Pod 1 without a shared pub/sub backbone
> (Redis / NATS). This is why SSE is deferred to Phase 2.

---

## 5. Agent Integration Patterns

```mermaid
flowchart TD
    AGT["Agentira Backend"]

    subgraph PA1["Pattern A1 · Daemon Wrapper"]
        PA1_R["WebhookReceiver :9111\ntriggered by backend POST"]
        PA1_E["Executor  pluggable\nZeroClaw · Antigravity CLI · direct LLM"]
        PA1_R --> PA1_E
    end

    subgraph PA2["Pattern A2 · Native Framework Webhook"]
        PA2_W["OpenClaw native endpoint\nmaps JSON payload to internal prompt"]
        PA2_I["OpenClaw agent loop\nzero coupling to Agentira internals"]
        PA2_W --> PA2_I
    end

    subgraph PA3["Pattern A3 · MCP Cron Poll"]
        PA3_C["ZeroClaw built-in cron\nevery N minutes"]
        PA3_T["agentira__get_notifications\nMCP tool call"]
        PA3_C --> PA3_T
    end

    subgraph PB1["Pattern B1 · Wake Poll"]
        PB1_W["User opens chat session"]
        PB1_C["get_notifications on wake\ndriven by system prompt instruction"]
        PB1_W --> PB1_C
    end

    subgraph PB2["Pattern B2 · SSE Session  Phase 2"]
        PB2_O["Agent opens GET /api/events/stream\noutbound connection · no inbound port needed"]
        PB2_P["Events pushed during active session\nreconnect triggers poll fallback via MCP"]
        PB2_O --> PB2_P
    end

    AGT -->|POST webhook| PA1_R
    AGT -->|POST webhook| PA2_W
    PA3_T -->|poll REST/MCP| AGT
    PB1_C -->|poll MCP| AGT
    PB2_O -->|SSE| AGT
```

| Pattern | Example frameworks | Inbound port | Push latency | Phase |
|---|---|---|---|---|
| A1 · Daemon wrapper | ZeroClaw, Antigravity CLI, custom | yes :9111 | sub-second | 1 |
| A2 · Native webhook | OpenClaw | yes (framework port) | sub-second | 1 |
| A3 · MCP cron poll | ZeroClaw built-in cron | no | N minutes | 1 — works today |
| B1 · Wake poll | VS Code Copilot, Antigravity IDE | no | next user interaction | 1 |
| B2 · SSE session | Any (Phase 2) | no | sub-second | 2 |

---

## 6. Data Model

### Project.webhook_config  (Text / JSON column, nullable)

If `null`, the dispatch layer applies `DEFAULT_WEBHOOK_RULES` (constant in
`agent_notifier.py`). No DB row needed for the default — changing defaults is a
code deploy, not a migration.

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

**Receiver groups:**

| Value | Who receives the event |
|---|---|
| `assignee` | The task's current assignee field |
| `bots` | All project members with `role = bot` |
| `members` | All project members regardless of role |

**Expansion path (no migration needed):** add `"condition"` or `"profiles"` keys to
individual rules as needed. When a proper `webhook_rules` table is warranted (cross-project
queries, per-rule metrics), the JSON schema maps directly to table columns.

**Validation:** `WebhookRule` and `ProjectWebhookConfig` Pydantic models validate the
JSON at the service layer before persistence and before dispatch.

---

### Profile.notification_transport  (Enum column, nullable)

```python
class NotificationTransport(str, enum.Enum):
    WEBHOOK = "webhook"
    SSE     = "sse"      # column exists now; dispatch logic ships Phase 2
    POLL    = "poll"
```

Resolution:

```python
def resolve_transport(profile) -> NotificationTransport:
    if profile.notification_transport:      # explicit always wins
        return profile.notification_transport
    if profile.webhook_url:                 # derive from URL presence
        return NotificationTransport.WEBHOOK
    return NotificationTransport.POLL       # safe default
```

---

### Webhook payload — structured fields only

No `message` field. Task titles, descriptions, and comments are user-supplied content.
Pre-composing them into a freeform string is a prompt injection vector. The receiving
agent constructs its own sanitised context from the structured fields.

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

---

### Daemon webhook receiver config  (agents/config.yaml)

Subscription rules live in the backend DB (project.webhook_config), not in the daemon.
The daemon YAML only carries the receiver-side settings:

```yaml
webhook:
  port: 9111    # 0 = disabled
  token: ""     # shared secret; empty = no auth (safe for localhost)
```

---

## 7. Implementation Phases

| Phase | Deliverables | Unlocks |
|---|---|---|
| **1a — Backend webhook infra** | `webhook_config` + `notification_transport` columns · Pydantic models · `get_webhook_targets()` · `notify_many()` · expanded events · webhook config REST endpoints | OpenClaw live via native webhook |
| **1b — Daemon webhook receiver** | `agents/webhook_receiver.py` · interrupt-aware sleep in daemon · YAML config | ZeroClaw + custom daemons via push |
| **1c — Poll fallback** | Daemon notification poll loop using existing `/api/notifications` | Resilience — no missed events |
| **2 — SSE** | Redis/NATS backbone · `GET /api/events/stream` · SSE client in Cat B agents | Sub-second push for VS Code / Antigravity during active sessions |
