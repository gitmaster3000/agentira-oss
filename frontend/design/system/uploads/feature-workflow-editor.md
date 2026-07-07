# Feature spec: Visual Workflow Editor (n8n-style canvas)

> **Audience.** UI designer / frontend agent picking up AP-250. This describes WHAT the user sees, WHAT they can do, WHAT it represents — enough to design without reading backend code. Backend reference: `templates/workflow/default.yaml`, `backend/forge/workflow.py`, `backend/gates.py`.

---

## 1. What the workflow is (user mental model)

Every Agentira project has a **workflow** — a pipeline that moves a task from idea to shipped, automatically.

Tasks flow left-to-right through **columns** (board statuses). On entry/exit of each column, the system can:
- Hand the task off to a specific agent role (planner → implementer → reviewer → docs)
- Run **gates** that check evidence before allowing the move
- Merge the agent's branch into main
- Dispatch the next agent automatically
- Recover when something goes wrong (bounce, re-dispatch, escalate)

The workflow is **the thing that makes Agentira self-sufficient**. Without it, every hand-off is manual. With it, the human only opens the laptop in the morning and reads the report.

Today, customers can't see what their project's workflow does. They edit a JSON field if they want changes. This feature is the **visual surface** that fixes that.

---

## 2. The headline experience

A single page on each project: **"Workflow"** in the Project nav.

Open it. See a **canvas** — your project's pipeline as a flow diagram. Nodes are columns. Arrows are hand-offs. Live work is highlighted with little task badges riding on the nodes ("3 in_progress, 1 in review").

Click a node → side panel opens, edit the role binding for that column, toggle gates, see recent activity.
Click an arrow → side panel opens, edit who reviews, edit the bounce policy.

Toggle the master switch at the top: **Workflow enabled** ON / OFF. When ON, the agents run the loop. When OFF, the board is manual-mode.

---

## 3. What's on the canvas

### 3.1 Column nodes (the boxes)

One node per status column. Default project flow:

```
[ backlog ] → [ todo ] → [ in_progress ] → [ review ] → [ done ]
```

Each node shows:
- **Column name** (`in_progress`, customer-renamable in future; system-defined today)
- **Assigned role chip** — who works tasks in this column ("planner" / "implementer" / "reviewer" / "documentation"). Click to change role assignment.
- **Live count** — "**3 tasks** in this column" with a small avatar stack of in-flight agents
- **Gate indicators** — small lock icons for active gates: 🔒 DoD checked · 🔒 Branch · 🔒 PR. Hover for the gate name; click the lock row to toggle gates for this column.
- **Auto-dispatch badge** — ⚡ when the column auto-dispatches the assigned role on arrival

Selected node → highlighted; side panel slides in from the right.

### 3.2 Hand-off arrows (the lines between)

Each arrow represents a `on_success` transition (what fires when a run in the upstream column finishes `succeeded`).

Arrow labels:
- **Role hand-off**: "→ assigns reviewer" / "→ assigns documentation"
- **Integrate marker**: "🔀 merges to main" (review → done in default flow)
- **Auto-dispatch**: ⚡ if `dispatch: true`

Arrow color/weight:
- **Solid** if the transition has fired in the last 24h
- **Dashed** if never fired (cold path)
- **Animated** when a task is currently traversing it

Selected arrow → side panel.

### 3.3 Live task badges (the riding pills)

Small pills perched on nodes / arrows, one per task in flight:
- `AP-234` style key + 12-char truncated title
- Avatar of the assigned agent
- Status dot (running / paused / blocked)
- Click → opens the task page

When a task is **mid-integration** (between review and done), the badge sits on the arrow with a 🔀 spinner.

When the bounce policy is firing (corrective re-dispatch), the badge shows ↩️ + a tooltip explaining "Gate failed, corrective run dispatched (1/2)".

---

## 4. The right-side inspector

Two inspector shapes — one for nodes, one for arrows. Both as overlay panels (slide-in from right, dim canvas behind, dismiss on click-out or Esc).

### 4.1 Node inspector — selected column

| Section | Contents |
|---|---|
| **Header** | Column name, status pill (system / customer-renamed), "× tasks in this column" |
| **Agent role** | Role binding for this column (planner / implementer / reviewer / documentation). Single agent or pool (Conductor picks among them). |
| **Entry gates** | Toggleable checks that run on arrival. Today: `has_dod`, `has_assignee` |
| **Exit gates** | Toggleable checks that run on attempt to leave. Today: `dod_all_checked`, `has_branch_or_pr`, `pr_url_set` |
| **Auto-dispatch** | Toggle: dispatch the assigned role immediately on entry vs wait for manual Run |
| **Integration policy** (review column only) | Target branch (default `main`), Push y/n |
| **Recent activity** | Last 5 transitions into/out of this column, with task key + actor + timestamp |

### 4.2 Arrow inspector — selected hand-off

| Section | Contents |
|---|---|
| **Header** | "From `in_progress` → To `review`" |
| **Trigger** | What fires it: "When implementer's run finishes `succeeded`" (read-only — system) |
| **Role bindings** | Edit `match` (substring list), `exclude_previous_assignee` (checkbox), `fallback` ("any" / "none") — the customer-overridable section |
| **Bounce policy** | `max_attempts` (default 2) + `window_minutes` (default 30). Editable per-project on the Workflow tab. |
| **Validation** | Show structured 422 errors inline if the edited overrides are invalid (Pydantic `Workflow` schema rejects them) |
| **Recent fires** | Last 10 transitions on this arrow with task key + outcome |

---

## 5. Top-bar controls (master switches + globals)

A small toolbar above the canvas:

- **Workflow enabled** (toggle) — `Project.workflow_enabled`. The kill switch. When OFF, the canvas dims to "read-only preview" and all auto-fires stop.
- **Gates enabled** (toggle) — `Project.gates_enabled`. Independent of workflow; gates can run on manual moves too.
- **Conductor active** (toggle, project-scoped or global) — `conductor_active`. The Conductor orchestrator's master switch.
- **Save** button — appears only when there are unsaved edits. Persists the customer-overridable surface via PUT `/api/projects/{id}/workflow`.
- **Reset to defaults** — discards customer overrides, falls back to `templates/workflow/default.yaml`.
- **View raw config** — collapsed by default; expands to show the resolved JSON (system flow + overrides applied) for power users / debugging.

---

## 6. Live state overlay

The canvas isn't static — it shows what's happening **right now**.

- **Task badges** on nodes/arrows update as tasks move (poll `/api/tasks` filtered by project; or subscribe to the Activity stream)
- **Bounce indicator** on the arrow when a corrective dispatch is mid-flight; ↩️ badge with a count "Attempt 1 of 2"
- **Escalation banner** at the top of the canvas when any task has hit "needs attention" status — "**AP-234 needs attention** — bounce budget exhausted. [view]" Dismissable per-task.
- **Integration in flight** — when the daemon is merging a branch (review→done), the arrow animates with a 🔀 spinner. Failure surfaces inline: "**Merge failed: merge_conflict on services.py**" with action buttons (View conflict / Re-run review).

---

## 7. Configuration boundaries (system vs customer)

This is critical for the UI to communicate honestly:

| What | Who owns it | UI behavior |
|---|---|---|
| Column names + order | **System** (`templates/workflow/default.yaml`) | Read-only badge "system column" |
| `on_success` semantics (what advances where) | **System** | Read-only |
| Role bindings (`match`, `exclude_previous_assignee`, `fallback`) | **Customer** | Editable inline |
| `workflow_enabled` | **Customer** | Toggle |
| `gates_enabled` | **Customer** | Toggle |
| Gate toggles per column | **Customer** | Checkbox row per gate (future — gate list is currently global) |
| `bounce.max_attempts`, `bounce.window_minutes` | **System today**, customer-editable later | Read-only chips on arrow inspector; "Edit" disabled with InfoTip "system config (Phase 1)" |
| Integration policy (target_branch, push) | **System** | Read-only |

**InfoTip wording:** Use a small ℹ icon on every system-owned field with text like "*System config — your customers can't break the pipeline by editing this*". This is the *product positioning*: customers can re-map roles, not rewire the engine.

---

## 8. Edge cases the UI must handle

| Situation | Visual treatment |
|---|---|
| Workflow disabled | Canvas dimmed 50%, "Workflow OFF — manual moves only" banner |
| No agents bound to a role | Arrow shows ⚠️ "No agent matches role `reviewer`" — clicking opens AgentsDashboard filtered to candidates |
| Reviewer = implementer (config violation) | Arrow shows 🚨 "reviewer must differ from implementer; check role config" |
| Customer JSON override invalid | Save fails with structured 422; inline field-level errors highlight the offending field; "Reset to defaults" pulses |
| Conductor offline | Top banner "Conductor not running — auto-dispatch paused. [restart](#)" |
| Long task title | Truncate at 32 chars with full text in tooltip |
| 20+ tasks in one column | Collapse badges to "+17 more" pill that opens a modal list |

---

## 9. Pages that link here

- **Project Overview** — small "workflow at a glance" card with a stripped-down pipeline (no inspector), click → opens the full Workflow page
- **Conductor page (Forge)** — "active workflows" list links to per-project Workflow pages
- **Task page** — a small "in pipeline" widget showing current column + next hand-off destination + arrow to "view workflow"
- **Activity feed** — workflow-actor rows (advance, bounce, escalate, integrate) deep-link to the relevant arrow/node on the canvas

---

## 10. What this replaces

| Old approach | New |
|---|---|
| Edit `Project.workflow_roles_json` raw in the DB or Settings JSON area | Click the arrow, edit role inline |
| Read `templates/workflow/default.yaml` to know the pipeline | See it on the canvas |
| Grep activity for "workflow: …" to debug | Visual feed on the relevant arrow/node |
| Tell user "the gate failed because DoD wasn't checked" via 422 string | Visual gate icon turns red, hover shows the failing check, click → opens the task to fix |

---

## 11. Interaction summary (for the designer's storyboard)

**Open path** — user clicks "Workflow" in project nav → canvas loads with live state → user sees pipeline + active tasks.

**Configure path** — user clicks the `in_progress → review` arrow → inspector slides in → user changes `match` from `["review"]` to `["senior", "lead"]` → "Save" button activates → user saves → toast confirms → canvas reflects new binding.

**Troubleshoot path** — banner says "AP-234 needs attention" → user clicks → canvas highlights the arrow where the bounce escalated → inspector shows the last 3 fires, last one was an escalation → user reads the gate failure → clicks task badge → goes to the task to resolve.

**Monitor path** — user opens the page during dispatch → watches a task badge ride the `in_progress → review` arrow live → sees the 🔀 merge spinner on review→done → done node lights up.

---

## 12. Out of scope for the first cut

- **Adding/removing columns** — system config for now; defer to a v2 once roles work is solid.
- **Per-column custom prompts** beyond the role's standing system_prompt — agents own prompts, columns just route work.
- **Multi-project workflow templates** library — defer.
- **Drag-to-reorder columns** — defer.
- **Reordering arrows** / cycle detection — single linear pipeline only.
- **Version history / rollback** of workflow edits — defer; just "Reset to defaults" for now.
- **Per-role agent pools with weighted round-robin** — single agent or `fallback: any` to least-loaded; no weights yet.

---

## 13. Visual / aesthetic notes

Per `agentira-frontend/CONVENTIONS.md` — use Material Design 3 token classes (`var(--accent-primary)`, `var(--text-secondary)`, `text-text-primary` Tailwind utilities). The canvas should feel **dense + technical, not playful**. Real-time motion belongs on the data (task badges riding arrows, merge spinners), not the chrome (no decorative gradients, no purple). Reference inspirations: n8n's editor, GitHub Actions' workflow runs view, Temporal's workflow visualizer.

`frontend-design` skill (AP-251) will apply once attached — until then, hold to the existing aesthetic.

---

*Source-of-truth files: `backend/forge/workflow.py` (driver), `backend/gates.py` (checks), `templates/workflow/default.yaml` (pipeline), `docs/PRD.md` §5 (overall self-sufficiency context).*
