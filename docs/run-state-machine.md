# Run state machine — canonical reference

**This is the single source of truth for run statuses and transitions.** The backend
`RunStatus` enum (`backend/forge/models.py`), the transition guard
(`backend/forge/run_state.py`), and the frontend `STATUS_CONFIG` (`RunDetail.jsx`,
`RunsDashboard.jsx`, `AgentDetail.jsx`) must all match this document. If you change the
state machine, change it here first, then propagate.

> Part of the **Runs & Chats Reconciliation** epic (AP-176). Replaces the previous 10-state
> enum where three transient states (`pausing`/`cancelling`/`resuming`) were handled
> inconsistently across backend and UI.

---

## Two orthogonal axes

A run has **two independent fields**. Do not conflate them.

| Axis | Field | Owner | Question it answers |
|---|---|---|---|
| **Status** | `RunStatus` | the system (process lifecycle) | *Where is this run in its execution?* |
| **Outcome** | `RunOutcome` | the agent (via `finish_run`) | *What did the agent conclude?* |

A run can be `status=completed` + `outcome=blocked` (process exited cleanly, but the agent
says it needs external help). Both are shown; **outcome is the primary badge** once present.

---

## Statuses (8)

| Status | Terminal? | Meaning |
|---|---|---|
| `ready` | no | Prepared (prompt persisted, agent assigned) but the user hasn't pressed **Start**. AP-112 prepare-then-start UX. |
| `pending` | no | Queued. Either about to dispatch, or waiting behind an active run in the same conversation (FIFO queue — a conversation is single-threaded). |
| `running` | no | The daemon is executing the subprocess. |
| `interrupting` | no | The user pressed **Stop** or **Discard**; the signal frame was sent and we're awaiting the daemon's ack. `interrupt_intent` (`pause`\|`discard`) decides where it lands. **Merges the old `pausing` + `cancelling`** — the daemon does the identical SIGTERM either way. |
| `paused` | no¹ | Stopped cleanly; the subprocess is gone, the session is captured. **Resumable.** |
| `completed` | yes | The process exited normally. |
| `failed` | yes | The process errored, the daemon died, or a dispatch never reached the daemon (reconciled). |
| `cancelled` | yes | The user discarded the run. |

¹ `paused` is *resumable-terminal*: no process is running, but **Resume** moves it back to
`pending`. It is not a dead end.

**Removed vs the old enum:** `pausing` → `interrupting`(pause), `cancelling` →
`interrupting`(discard), `resuming` → removed (Resume is just `paused → pending → running`).

---

## Outcomes (4) — orthogonal, set by the agent

`succeeded` · `blocked` · `needs_input` · `failed`. Set via the `finish_run` MCP tool;
never set by status transitions (except a safety net: a `cancelled`/`failed` run with no
outcome is stamped `outcome=failed`).

---

## Transition table

Every legal transition, and **who triggers it**. Anything not listed is illegal and the
transition guard rejects it.

| From | To | Trigger | Notes |
|---|---|---|---|
| — | `pending` | system | A dispatch (chat or auto). |
| — | `ready` | user | A *prepared* run awaiting Start (AP-112). |
| `ready` | `pending` | user — **Start** | |
| `ready` | `cancelled` | user — **Discard** | Never ran. |
| `pending` | `running` | daemon — first event / start | |
| `pending` | `cancelled` | user — **Discard** | Discard a queued run before it dispatches. |
| `pending` | `failed` | reconciler | Dispatch never reached a daemon. |
| `running` | `interrupting` | user — **Stop** (intent=pause) or **Discard** (intent=discard) | |
| `running` | `completed` | daemon — complete(success) | |
| `running` | `failed` | daemon — complete(error) / reconciler | Daemon died or errored. |
| `interrupting` | `paused` | daemon ack, or reconciler timeout | when `interrupt_intent=pause` |
| `interrupting` | `cancelled` | daemon ack, or reconciler timeout | when `interrupt_intent=discard` |
| `paused` | `pending` | user — **Resume** | Re-dispatch with `--resume`; then `pending → running` as usual. |
| `paused` | `cancelled` | user — **Discard** | Abandon a paused run. |

**Terminal states** (`completed`, `failed`, `cancelled`) have no outgoing transitions.
"Restart" is a *new* run, not a transition.

```
                ┌────────── user Start ──────────┐
   ready ───────┤                                 ▼
     │ Discard  └─────────────────────────────► pending ──── daemon ───► running
     ▼                                            │  ▲                     │
  cancelled ◄──── Discard ───────────────────────┘  │ Resume              │
     ▲                                               │                     │
     │                       paused ─────────────────┘                     │
     │                         ▲                                           │
     │           intent=pause  │   daemon ack / reconciler                 │
     │                    interrupting ◄──── Stop / Discard ───────────────┤
     │  intent=discard         │                                           │
     └──── daemon ack ─────────┘            daemon complete                │
                                            ┌──────────────┬───────────────┘
                                            ▼              ▼
                                        completed        failed
```

---

## Allowed user actions per status

The UI shows exactly these controls per status. Keep `STATUS_CONFIG` consistent with this.

| Status | Start | Stop (pause) | Resume | Discard | Restart |
|---|:--:|:--:|:--:|:--:|:--:|
| `ready` | ✅ | — | — | ✅ | — |
| `pending` | — | — | — | ✅ | — |
| `running` | — | ✅ | — | ✅ | — |
| `interrupting` | — | — | — | — | — |
| `paused` | — | — | ✅ | ✅ | — |
| `completed` | — | — | — | — | ✅ |
| `failed` | — | — | — | — | ✅ |
| `cancelled` | — | — | — | — | ✅ |

- **Stop** = pause + preserve session, **always** resumable. One meaning everywhere.
- **Discard** = throw the run away (the old "cancel"), now explicit and secondary.
- **Resume** = continue a paused run via `--resume`.
- `interrupting` shows a non-interactive "Stopping…" indicator.

---

## After the run: the workflow driver

When a run finishes `succeeded` on a workflow-enabled project, the driver
(`backend/forge/workflow.py`, policy in `templates/workflow/default.yaml`)
decides what happens to the **task**. In order:

1. **Rejection hand-back (AP-252).** If the task was deliberately moved
   *backward* during the run (a reviewer rejecting work, a human demoting it —
   detected from `task.move` rows in the Activity ledger), the driver does NOT
   try to advance. Per the YAML `rejection:` policy it reassigns the task to
   whoever owes the fix (`previous_agent` = the implementer, or a configured
   role) and dispatches a corrective run carrying the rejecter's latest
   comment (`templates/workflow/prompts/rejection_handback.md`).
2. **Gate check + advance.** Otherwise the configured `on_success` advance is
   attempted, gate-checked (`backend/gates.py`).
3. **Bounce (AP-231).** "Succeeded but gate failed" re-dispatches the same
   agent with a corrective prompt (`gate_bounce.md`).
4. **Escalation.** Bounces and hand-backs share one budget
   (`bounce.max_attempts` runs per task in `bounce.window_minutes`); when it's
   spent — or no hand-back target resolves — the task gets a 🚩 needs-attention
   comment and admins are notified. The Conductor's progress watchdog is the
   recovery layer above that.

---

## Liveness

"Is the agent working right now?" = status ∈ {`pending`, `running`, `interrupting`}. This is
**server-pushed** over the conversation WS channel — never inferred from message age or
polling. A run whose daemon stops reporting (`Run.last_heartbeat_at` stale) is reconciled to
`failed`, so the indicator can never stick.
