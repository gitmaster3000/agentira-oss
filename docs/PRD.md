# Agentira PRD — current product surface (for redesign reference)

> **Purpose.** A faithful snapshot of every feature, page, setting, model, workflow, and MCP tool that exists in Agentira today (2026-06-11). Read this before redesigning any UI so the new surface covers what's actually there. **No aspirational features**; what is described here is in production code on `main` / `main-2`. Out-of-scope items are listed explicitly at the end.

---

## 1. Product identity

**One-liner.** Agentira is a self-hosted platform that orchestrates AI coding agents on real software projects, with traceable runs, verifiable artifacts, and a Kanban board that reflects reality.

**Two products under one umbrella ("Flowty"):**

| Product | Mental model | URL prefix |
|---|---|---|
| **Flowty Studio** | Project / task / board management (where humans plan work) | `/studio/*` |
| **Flowty Forge** | Agent orchestration: agents, runs, conversations, dispatch | `/forge/*` |

Shared backend (FastAPI + SQLAlchemy + SQLite/Postgres), shared identity, shared notifications, shared activity log. The two product surfaces share a top-bar app switcher.

**Audiences.**
- **Humans** — sign in via JWT/OAuth, use the web UI + REST.
- **Agents** — connect via MCP (HTTP+Bearer or stdio). Every tool call is RBAC-checked against the agent's API key.

---

## 2. Architecture & core concepts

### 2.1 Execution model (ADR 009)

| Concept | What it is | Lifetime |
|---|---|---|
| **Conversation** | The agent's working memory for one *scope* (`task:T`, `chat:project:P`, `chat:default`). Keys claude `--resume`. | Per (agent, scope). Long-lived. |
| **Turn** | One dispatch (user message + agent response, single `trace_id`). Atomic, durable, stoppable. | Per dispatch. |
| **Run** | An *emergent span* grouping the turns of one work episode. Carries verdict, accounting, diff, artifacts. | Per work episode. |
| **Artifact** | Concrete deliverable on a run (`pr`, `commit`, `file`, `log`, `report`, `url`). | Forever, attached to its run. |

### 2.2 Trust architecture

> The system verifies. The agent executes. The human audits.

- **Agents cannot assert completion.** Forward state transitions require evidence the server can independently check (DoD checkboxes, branch refs, PR URLs, merged-status).
- **Every claim is checkable.** PR links validated; tests run as real CI; commit SHAs verified to exist.
- **The container is the security boundary** — long-term. Today's interim boundary is per-agent home dirs at `0o700` (AP-240), per-task git worktrees, and MCP role tokens.

### 2.3 Three-layer Toolset model (`docs/mcp_layering.md`)

Every dispatch composes tools from three layers, rendered in the AgentDetail Toolset section:

| Layer | Owner | Examples |
|---|---|---|
| **L1 · Runtime built-ins** | Runtime binary | claude-code: Read, Edit, Bash, Grep, Glob, WebFetch, Task, TodoWrite, Skills loader, hooks |
| **L2 · Host config** | User's machine | `~/.claude.json` MCP servers, `~/.claude/CLAUDE.md`, `~/.claude/skills/`, plugins |
| **L3 · Agentira-managed** | Per-agent, ephemeral | `agentira` MCP (always), `memory` MCP (always), opt-in servers, custom JSON, per-agent secrets |

L3 is the only layer Agentira writes to. L1 + L2 are surfaced for transparency. **Skills layer (AP-251) will extend this model.**

### 2.4 Containment / sandbox modes

Per-(workspace | project | agent) `sandbox_mode`, resolved at dispatch:

| Mode | Effect |
|---|---|
| `off` | No containment beyond OS perms. |
| `cwd` | Agent confined to its workdir (best-effort, runtime-dependent). |
| `strict` | Stricter restrictions; runtime-dependent. |
| `container` | Reserved for Phase 2 (bubblewrap / sandbox-exec / Docker). |

---

## 3. Studio surface

### 3.1 Public / auth pages

| Route | Page | Function |
|---|---|---|
| `/welcome` | `Landing.jsx` | Marketing landing |
| `/login` | `Login.jsx` | Username/password + Google + GitHub buttons |
| `/signup` | `Signup.jsx` | Username/password sign-up |
| `/auth/github/callback` | `GitHubCallback.jsx` | OAuth round-trip |

Auth backed by JWT (`backend/jwt_auth.py`) with mandatory `JWT_SECRET` in prod (AP-194). OAuth providers configured via `GOOGLE_*` / `GITHUB_*` env vars. API exposes `/auth/config` so the UI knows which buttons to show.

### 3.2 Workspace-level

| Route | Page | Contents |
|---|---|---|
| `/studio` | `StudioDashboard.jsx` | Workspace home: projects card grid, recent activity feed, quick "New Project" |
| `/studio/settings` | `Settings.jsx` | API key, profile (display_name, avatar, webhook_url), Service Accounts (api-key-only identities, no runtime), Notification transport preference |
| `/activity` (via dashboard) | `ActivityFeedPage.jsx` | Workspace-wide tamper-evident activity log |

**Workspace settings include:**
- User profile: `display_name`, `email`, `avatar_url`, `webhook_url`, `notification_transport`
- **API key** (regenerable) — used for MCP auth
- **Service Accounts** — bot-shaped identities with API keys but no runtime (for external MCP clients like Cursor / Claude Desktop)

### 3.3 Project shell (`/studio/project/{id}/*`)

Wraps every project surface with a left nav: **Overview, Board, Backlog, Roadmap, Settings**. Implemented by `ProjectLayout.jsx`.

#### 3.3.1 Project Overview — `ProjectOverview.jsx`
- Stats cards: task counts per status, members count, attachments
- Recent activity feed (per-project filter)
- Pinned attachments preview

#### 3.3.2 Board — `Board.jsx`
- Kanban view of the project's task statuses (default columns: **backlog, todo, in_progress, review, done**)
- Drag-and-drop between columns; backend enforces transition permissions per role + gate engine
- Per-task card shows: key (`AP-123`), title, priority pill, assignee avatar, DoD progress, branch+PR indicators, epic chip
- Filter bar: assignee, priority, epic, tag
- "+ New Task" per-column quick add

#### 3.3.3 Backlog — `Backlog.jsx` (also: `BacklogBoard.jsx`)
- Flat list of all project tasks, sortable + filterable
- Inline edit: title, priority, assignee, status, epic, tags
- Bulk select + bulk move/assign
- "Create task" modal

#### 3.3.4 Roadmap — `Roadmap.jsx`
- Timeline / Gantt-ish view using `start_date` + `due_date`
- Group by: epic, status, assignee, priority
- Read-only today; drag-to-adjust dates not implemented

#### 3.3.5 Project Settings — `ProjectSettings.jsx`
Tabbed/section view; every editable field:

| Section | Field | What it does |
|---|---|---|
| **Basics** | `name`, `description`, `key_prefix` | Identity; `key_prefix` drives task keys like `AP-123` |
| | `conventions_md` | Markdown materialized into every dispatch as `.agentira/CONVENTIONS.md` + sibling `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` symlinks |
| **Workspace** | `workspace_kind` ∈ {`git`, `local_folder`, `sandbox`} | How the daemon provisions the working copy. Derived from repo presence: any attached repo (project `repo_url` or a `project_repos` row with a URL) means `git` — a stored `sandbox` is ignored, since it would drop the agent into an empty folder (AP-414). Overridable in Project Settings → Repos → danger zone. |
| | `repo_path` | Local host filesystem path (same-machine) |
| | `repo_url` | Remote git URL (daemon clones into `~/.agentira/sources/`) |
| | `sandbox_mode` ∈ {`""` inherit, `off`, `cwd`, `strict`, `container`} | Project-level containment override |
| **Repos** (multi-repo, AP-154/197) | per-repo: `name`, `repo_url`, default branch | A project can declare N repos; tasks pick one via `repo_name` |
| **Members** | profile picker, role assignment | Add/remove members; RBAC per role (admin/member/viewer/bot) |
| **Workflow engine** | `workflow_enabled` (bool) | Opt-in to the self-sufficiency loop (Conductor + driver) |
| | `workflow_roles_json` (JSON) | Per-project role overrides (who fills `reviewer` / `documentation` / `implementer`) |
| **Gates** | `gates_enabled` (bool) | Enforce evidence checks on every transition |
| **Conductor** | `wake_on_comment` (bool) | A comment on a task wakes the assigned agent |
| **Templates** | `template_name` (set on creation) | Project-template provenance |
| **Webhooks** | `webhook_config` (JSON) | Per-event webhook rules |
| **Attachments** | upload area | Briefs, designs, brand guides — agents read text inline, fetch binaries with their key |

### 3.4 Task & Epic detail

#### 3.4.1 Task page — `/studio/tasks/{id}` (`TaskPage.jsx`)
Editable inline fields:
- `title`, `description` (markdown)
- `status`, `priority`, `assignee`
- `epic_id` (epic picker)
- `tags` (chips)
- `start_date`, `due_date`
- **DoD checklist** — `dod_items: [{text, checked}]`, inline-editable, drives the workflow gate `dod_all_checked`
- `branch` (mirrored from worktree at dispatch), `pr_url`
- `repo_name` (single repo) or `repos_json` (multi-repo, deprecating per 2026-06-10 policy)
- **Comments / activity feed** — every action structured, with `actor`, `action`, `detail`, optional `diff` JSON
- **Attachments** — upload, list, download
- **@mention autocomplete** in comments (AP-186)
- **Linked commits / PRs** — `TaskCommit` rows showing sha, message, author, branch, kind (commit | pr), pr_state, pr_number
- **Linked runs** — list of Forge runs that touched this task, with status badges

#### 3.4.2 Epic page — `/studio/epics/{id}` (`EpicPage.jsx`)
- Epic basics: `title`, `description` (markdown, inline-editable per AP-183), `color`
- Member-style assignee (creator)
- Tasks list (scoped to the epic)
- Activity feed

### 3.5 Status columns + transitions

Default statuses with positions: **backlog (0), todo (1), in_progress (2), review (3), done (4)**.

Allowed transitions (manual moves; gates run on each):
- backlog ↔ todo
- todo ↔ backlog
- todo → in_progress
- in_progress → review
- in_progress → backlog
- review → done
- review → in_progress (reviewer rejection)
- done → backlog (rare; corrective)

Each transition is permission-gated (`transition:from:to` codename in `permissions` table) AND evidence-gated (gate engine).

### 3.6 Notifications surface

- **Bell icon** in top nav with unread count
- **Inbox panel** — click bell → list of notifications, mark read, click-through to source task/run
- **Auto-emitted events**: run started / ready / completed / failed, agent blocked, agent permission request (planned), gate failures, integration results, "needs attention" escalations
- **Push + poll hybrid** per ADR-007 (server pushes when client is connected; client polls fallback)

### 3.7 Markdown rendering

Shared `<Markdown>` component renders task descriptions, epic descriptions, comments, run summaries — `react-markdown` with custom theme tokens.

---

## 4. Forge surface

### 4.1 Forge shell (`ForgeLayout.jsx`)

Left nav: **Overview, Agents, Runs, Conductor, Runtimes, Settings**. Header carries the same notification bell + app switcher as Studio.

| Route | Page |
|---|---|
| `/forge` | `ForgeOverview.jsx` |
| `/forge/agents` | `AgentsDashboard.jsx` |
| `/forge/agents/{id}` | `AgentDetail.jsx` |
| `/forge/runs` | `RunsDashboard.jsx` |
| `/forge/runs/{id}` | `RunDetail.jsx` |
| `/forge/conductor` | `ConductorPage.jsx` |
| `/forge/runtimes` | `RuntimesDashboard.jsx` |
| `/forge/settings` | `ForgeSettings.jsx` |

### 4.2 Agents Dashboard

Grid of agent cards with:
- Identity (avatar, name)
- Runtime + model
- Status pill (online / offline / running)
- In-flight count vs `max_concurrent_runs`
- Default project chip
- Quick-open / chat actions
- "+ New Agent" modal (`CreateAgentModal.jsx`)

### 4.3 Agent Detail — every per-agent knob

Single-page detail with sections (every settable field is here — full list maps to `AgentUpdate` Pydantic schema):

#### Identity
- `name`, `display_name`, `avatar_url`, `personality`

#### Runtime binding
- `runtime_id` (claude / openclaw / ollama)
- `model` (e.g. `claude-opus-4-8`, `claude-sonnet-4-6`, `qwen-3.6`)
- `runtime_type`, `runtime_url`, `runtime_gateway_token`, `runtime_hooks_token`, `runtime_agent_name` (openclaw)
- `executor_type` (http / cli)
- `webhook_url` (outbound)

#### System prompt (prompts-are-config)
- `system_prompt` — Markdown editor, set-if-empty seeded from `templates/agents/<role>.md`, **user owns it after first edit**

#### Toolset (the three-layer panel, the canonical example for redesign)
- **Layer 1 · Runtime built-ins** — read-only chips, daemon-reported
- **Layer 2 · Host config** — read-only chips, daemon-discovered (`host_mcp_servers`, `host_md_files`)
- **Layer 3 · Agentira-managed** — toggleable chips:
  - `mcp_servers` (list of opt-in server names)
  - `mcp_disabled` (built-ins explicitly turned off — `agentira`, `memory`)
  - `mcp_strict` (bool — when true, daemon passes `--strict-mcp-config`, hiding L2 entirely)
  - `mcp_config_override` (raw JSON for `mcpServers`)
- **Resolved config viewer** — the full merged JSON the agent will see, with secrets redacted

#### Concurrency
- `max_concurrent_runs` (env-configurable cap per AP-201)

#### Conductor settings (only on the Conductor agent profile)
- `conductor_enabled` (boolean opt-in per regular agent)
- `conductor_active` (master switch on the Conductor itself)
- `conductor_tick_seconds` (deterministic queue tick cadence)
- `conductor_plan_interval_minutes` (LLM planning turn cadence)
- `conductor_report_time` (daily report time, local)
- `conductor_report_enabled` (bool)

#### Bindings
- `default_project_id` (which project this agent picks work from)
- `schedule_cron` (optional cron for scheduled wake-ups)
- `home_path` (override `~/.agentira/agents/<id>/home`)

#### Secrets
- `env_secrets` — JSON `{KEY: VALUE}` injected at dispatch (GH_TOKEN, OPENAI_API_KEY, etc.)

#### Sandbox
- `sandbox_mode` (agent-level override of project)

#### Chat (`/forge/agents/{id}` includes a chat panel — `FloatingChat.jsx`)
- Per-scope chat (`chat:default`, `chat:project:P`, `task:T`)
- Mid-flight Stop / Pause / Resume / Discard
- Conversation switcher (list of past scopes)
- Clear conversation (resets `--resume` handle)
- Recent runs side panel

#### Recent activity
- Last 10 runs with status badges + outcome

### 4.4 Runs Dashboard

List of all runs, filter bar: status, agent, project, outcome, has-diff, has-PR. Each row:
- Run id (short)
- Agent + task title
- Status pill (PENDING, RUNNING, COMPLETED, FAILED, PAUSED, CANCELLED, INTERRUPTING)
- Outcome pill (succeeded / failed / blocked / needs_input)
- Tokens (in / out), cost ($USD)
- Duration
- Branch + PR link
- "Active runs" indicator badge in top nav (header)

### 4.5 Run Detail

Per-run page with sections:

| Section | Contents |
|---|---|
| **Header** | id, agent, task, status, outcome, branch, PR, restart button |
| **Conversation** | Message thread (user turns + agent responses + tool calls), scoped to this run |
| **Changes** | `git diff` captured by daemon (`diff_stat` summary + full patch up to ~50KB) |
| **Artifacts** | Registered via `register_run_artifact` — kinds: `pr`, `commit`, `file`, `log`, `report`, `url` |
| **Events** | Live event stream from the daemon (per-trace tail) |
| **Diagnostics** | `diagnostics_json`: `{exit_code, stderr_tail, last_events_tail, captured_at}`; `materialize_reason`; per-run logs paths (`stdout.log`, `stderr.log`, `meta.json`); "where it worked" path; conversation-resume verdict |
| **Run summary** | Agent-provided summary on `finish_run` |
| **Cost panel** | Tokens (in / out), $USD, model |

**Run lifecycle states (`RunStatus`):** PENDING · READY · RUNNING · PAUSED · INTERRUPTING · COMPLETED · FAILED · CANCELLED.

**Outcomes (`RunOutcome` — agent-declared):** succeeded · failed · blocked · needs_input.

**Restart button** on terminal runs: same (task, agent), fresh dispatch with prior-outcome context.

### 4.6 Conductor page

Overview of the orchestrator agent's state:
- Active toggle (`conductor_active`)
- Cadence config (tick / plan / report)
- Latest tick result (token-free): dispatched / skipped / reconciled
- Latest planning turn result (LLM): unassigned count, agents seen
- Latest progress check result (LLM, AP-232 watchdog): stalled count
- Latest daily report (link)
- Survey: every conductor-enabled agent, in-flight load, next eligible task

### 4.7 Runtimes Dashboard

Lists every runtime the daemon has registered:
- Provider (claude / openclaw / ollama / codex / gemini)
- Binary path / gateway URL
- Version
- Capabilities (`RESUME`, `STREAM_EVENTS`, `STOP`, `PAUSE`, `TOOLS`, `MCP`)
- Models advertised
- Status (online / offline)
- Daemon connections (which host registered it)

### 4.8 Forge Settings

- Default model, pricing catalog (per-provider price tables)
- OpenClaw overview & sync
- Models catalog per provider + refresh
- Scheduler refresh

### 4.9 MCP Servers registry — `/forge/mcp-servers`

Registry of opt-in MCP servers available across all agents (workspace-shared definitions). Per server: name, transport, command/url, env requirements, description, "enable for this agent" affordance from Agent Detail.

---

## 5. Self-Sufficiency Workflow Engine

The crown jewel — built but only partially activated. Driven by `templates/workflow/default.yaml` (system config) + per-project `workflow_roles_json` (customer config) + `backend/forge/workflow.py` (the deterministic driver) + `backend/forge/conductor.py` (LLM planning/judgment) + `backend/gates.py` (evidence checks).

### 5.1 The pipeline (default)

```
backlog → todo → in_progress → review → done
            │         │           │       │
          (manual)   plan      review     docs
                                merge
```

### 5.2 What fires automatically

| Trigger | Action | Owner |
|---|---|---|
| Conductor planning interval | LLM assigns unassigned `todo` tasks to agents by specialty | Conductor (LLM) |
| Conductor tick (every N sec) | Dispatch assigned `todo` work to free agents | Conductor (token-free script) |
| `finish_run(succeeded)` | `advance_after_run` — run gates → move column → reassign role → dispatch hand-off | Workflow driver |
| `in_progress → review` succeeded | Assign **reviewer** (`exclude_previous_assignee: true`), dispatch immediately | Workflow driver |
| `review → done` succeeded | Daemon merges branch into `main` (`--no-ff`) + pushes to origin | Daemon `integrate.py` |
| Task lands in `done` | Dispatch **documentation** role (write docs about what shipped) | Workflow driver |
| Run succeeded but gate fails | Post missing evidence + re-dispatch same agent (max 2 attempts in 30 min) → escalate "needs attention" + notify admins | Workflow `_bounce_gate_failure` (AP-231) |
| Stalled task (no activity 30 min OR last run failed) | Conductor LLM reads stalled list, decides re-dispatch / reassign / escalate per task | Conductor `run_progress_check_turn` (AP-232, not yet wired) |
| Daily report cadence | Conductor compiles per-project digest, structured JSON, narrative paragraph | Conductor `run_daily_report` |

### 5.3 Gates (`backend/gates.py`)

Every transition runs structured checks; failures block the move with a 422 carrying `failed_gates`:

| Check | What it asserts |
|---|---|
| `has_dod` | `dod_items` non-empty |
| `has_assignee` | `task.assignee` set |
| `dod_all_checked` | every `dod_items[i].checked == true` |
| `has_branch_or_pr` | `task.branch` or `task.pr_url` non-empty |
| `pr_url_set` | `task.pr_url` is a valid URL |

Gates are project-level opt-in (`Project.gates_enabled`). The workflow driver also runs them at advance time and bounces on failure.

### 5.4 Role bindings

Customer-overridable per project (`workflow_roles_json`). Default:

| Role | Name match | Exclude previous assignee | Fallback |
|---|---|---|---|
| `reviewer` | review · senior · lead · architect | **true** | `none` |
| `documentation` | doc · documentation · writer | false | `none` |

`fallback: any` → pick least-loaded eligible candidate. `none` → leave task un-advanced.

### 5.5 Bounce policy

```yaml
bounce:
  enabled: true
  max_attempts: 2        # original + one corrective
  window_minutes: 30
```

Customer can disable; system constants stay system-owned.

---

## 6. MCP surface (the agent's API)

Single MCP server at `/mcp` (HTTP+Bearer) and stdio fallback. Every tool call is RBAC-checked. **~40 tools** organized by domain:

### 6.1 Identity
`get_me`, `update_profile`, `login`, `list_permissions`, `list_roles`, `get_my_involvement`

### 6.2 Projects
`list_projects`, `get_project`, `create_project`, `update_project`, `delete_project`, `add_project_member`, `remove_project_member`, `list_project_repos`, `get_project_activity`

### 6.3 Epics
`list_epics`, `create_epic`, `update_epic`, `delete_epic`

### 6.4 Tasks
`list_tasks`, `get_task`, `create_task`, `update_task`, `move_task`, `delete_task`, `get_task_activity`, `add_comment`, `get_activity`, `list_statuses`

### 6.5 Attachments
`create_attachment`, `read_attachment`, `delete_attachment` (each supports the relevant task, project, or epic scope)

### 6.6 Runs (agent-facing)
`get_run`, `get_run_events`, `get_run_diagnostics`, `register_run_artifact`, `finish_run`

### 6.7 Notifications
`get_notifications`, `mark_notification_read`

Every tool's authoritative description lives in `backend/mcp_server.py`. RBAC enforcement applies the same `transition:from:to` permission scheme used by the UI — agents can't move tasks the UI wouldn't let them.

---

## 7. Daemon (host-side, what the user doesn't see)

The daemon (`agentira-cli`) runs on the user's machine; it's the thing that actually spawns agent runtimes. UI surfaces affect daemon behavior at dispatch.

**What the daemon owns:**
- Per-agent home dirs (`~/.agentira/agents/<agent_id>/home/`) at mode `0700` (AP-240)
- Source clones (`~/.agentira/sources/<url-slug>/`) — one per project remote
- Per-task git worktrees branched off the source
- Per-run log dir (`~/.agentira/runs/<run_id>/`)
- Materialized conventions (`.agentira/CONVENTIONS.md` + `AGENTS.md` symlink)
- Materialized MCP config (tempfile, passed via `--mcp-config`)
- Materialized memory dir (`~/.agentira/memory/<agent>/<project>/`)
- Subprocess management + heartbeats + orphan reaping
- Branch integration (merge `--no-ff` + push) at workflow's request

**Workflow-driver-as-Conductor-helper-script** lives on the backend; daemon handles the *deterministic actions* (clone, worktree, spawn, merge).

---

## 8. Auth, RBAC, observability

### 8.1 Auth
- Username/password (`POST /api/login`)
- Google OAuth (`POST /api/auth/google`)
- GitHub OAuth (`POST /api/auth/github` + `/auth/github/callback`)
- JWT issuance with mandatory `JWT_SECRET` in prod (AP-194)

### 8.2 RBAC
- Roles: `admin`, `member`, `viewer`, `bot`
- Per-permission rows in `permissions` table (e.g. `transition:in_progress:review`)
- Profile-level extra permissions (`profile_permissions` table)
- Service accounts: api-key-only identities (bots) with no runtime; appear under Settings → Service Accounts

### 8.3 Activity log
Every state change writes an `Activity` row with `{actor, action, detail, diff: JSON}`. Tamper-evident in the sense that the rows are append-only; surfaced per-project, per-task, and workspace-wide.

### 8.4 Audit data on Run
Per-run captured: `materialize_reason`, `worktree_path`, `worktree_branch`, `session_id`, `diff` + `diff_stat`, `artifacts_json`, `last_heartbeat_at`, `diagnostics_json`, `initial_prompt`.

---

## 9. Reference matrices

### 9.1 Project model — every field

| Field | Type | Default | Notes |
|---|---|---|---|
| `id` | str(12) | autogen | primary key |
| `name` | str(120) | required | |
| `description` | text | "" | markdown |
| `key_prefix` | str(10) | `PROJ` | task key prefix |
| `next_task_number` | int | 1 | monotonic counter |
| `repo_path` | str(500)? | null | local FS path |
| `repo_url` | str(500)? | null | remote git URL |
| `workspace_kind` | str(20)? | null→derived | `git` / `local_folder` / `sandbox`; repo presence beats a stored `sandbox` (AP-414) |
| `conventions_md` | text? | null | materialized at dispatch |
| `template_name` | str(120)? | null | provenance |
| `ac_check_types_json` | text? | null | per-template AC checks |
| `sandbox_mode` | str(20)? | null | inherits agent / workspace |
| `gates_enabled` | bool | false | gate engine opt-in |
| `workflow_enabled` | bool | false | workflow engine opt-in |
| `workflow_roles_json` | text? | null | customer role overrides |
| `wake_on_comment` | bool | false | comment dispatches agent |
| `webhook_config` | text? | null | per-event webhook rules |

### 9.2 Task model — every field

| Field | Type | Default | Notes |
|---|---|---|---|
| `id` | str(12) | autogen | |
| `key` | str(20) | autogen | e.g. `AP-123` |
| `project_id` | FK | required | |
| `epic_id` | FK? | null | |
| `title` | str(255) | required | |
| `description` | text | "" | markdown |
| `status_id` | FK | required | |
| `priority` | enum | medium | critical / high / medium / low |
| `assignee` | str(120) | "" | agent or human name |
| `creator` | str(120) | "" | |
| `tags` | str(500) | "" | comma-sep |
| `dod_items` | text? | null | JSON `[{text, checked}]` |
| `branch` | str(255) | "" | mirrored from worktree |
| `pr_url` | str(500) | "" | |
| `repo_name` | str(60)? | null | which project repo |
| `repos_json` | text? | null | deprecating (1-task-1-repo policy) |
| `start_date` / `due_date` | datetime? | null | for roadmap |

### 9.3 Agent / Profile — every settable field

See `AgentUpdate` Pydantic schema. Categories: identity, runtime, prompts, toolset (L3), concurrency, conductor cadence, bindings, secrets, sandbox.

### 9.4 Run lifecycle

```
        ┌──── PENDING ───── READY ───── RUNNING ─┐
        │                                        ├── INTERRUPTING ──┬─ PAUSED ─┐
        │                                        │                   └─ CANCELLED
        │                                        ├── COMPLETED
        │                                        └── FAILED
```

Outcome (agent-declared, orthogonal to status): `succeeded` / `failed` / `blocked` / `needs_input`.

### 9.5 Notification types

- `forge.run.created` / `ready` / `started` / `completed` / `failed`
- `forge.run.blocked`
- `workflow.gate_failed`
- `workflow.needs_attention` (bounce exhausted)
- `workflow.integration_failed`
- Studio: comment mention, task assigned, task moved (membership-filtered)

### 9.6 Templates (config, not code)

```
templates/
├── agents/                    # default agent system prompts (seed-once)
│   ├── backend-implementer.md / .yaml
│   ├── frontend-implementer.md / .yaml
│   ├── reviewer.md / .yaml
│   ├── planner.md / .yaml
│   ├── devops.md / .yaml
│   └── conductor.md / .yaml
├── conductor/                 # Conductor's per-turn prompts
│   ├── system_prompt.md
│   ├── planning_turn.md       # who-gets-what assignment
│   ├── progress_check.md      # AP-232 stalled-task judgment
│   └── daily_report.md        # executive briefing
└── workflow/
    ├── default.yaml           # the system pipeline (not customer-editable)
    └── prompts/
        └── gate_bounce.md     # corrective re-dispatch prompt (AP-231)
```

---

## 10. Explicitly NOT in the product today

- **Generic work management** (marketing, video, SAP, etc.) — architecturally enabled by templates; not built.
- **Template marketplace** — Series A feature.
- **Team features / multi-user collaboration on the same task** — solo / async only.
- **Mobile native app** — PWA only.
- **Container Phase 2** (bubblewrap / sandbox-exec / Docker per agent) — on roadmap.
- **One-click daemon installers** — manual `pip install -e agentira-cli/` today.
- **Sandbox enforcement Phase 2** — config exists, enforcement deferred.
- **Multi-repo Phase 2** (materialize every declared repo into the agent's cwd as named subdirs) — partially shipped (AP-236), still has edge cases (AP-237 follow-ups).
- **Real-time collaboration / multiplayer editing** — not planned.
- **Skills as first-class agent attribute** — AP-251 in backlog.
- **Visual workflow editor (n8n-style)** — AP-250 in backlog.
- **Per-repo agent access controls** — AP-246 was filed, abandoned in favor of AP-250.
- **Verified state machine: server-side commit verification at finish_run** — AP-81 still open.
- **GitHub PR reconciler** — AP-85 still open.
- **Autonomy dial / permission popups** — `c10ea54a1209` epic, not built.
- **Custom field builder** — not planned.
- **Attachment object storage** (S3 / Railway Volume) — local FS today.

---

## 11. Design notes for the redesign

- **Don't lose the three-layer Toolset visualization.** It's the load-bearing example of how Agentira composes on top of runtimes, not around them. Skills (AP-251) will use the same shape.
- **The board (`Board.jsx`) is the *primary* surface** — users live there. Card density matters.
- **Run Detail is currently a debug dump** — AP-188 already reframes it into "Where it worked / Conversation / Logs / Advanced." Honor that grouping.
- **Inline editing is the canonical pattern** for single-field changes (see TaskPage). Modals are reserved for multi-field creation and destructive confirmations.
- **Two products, one mental switch** — the app switcher is what's between Studio (planning) and Forge (execution). Don't blur them.
- **Conventions live in `CONVENTIONS.md` (`agentira-frontend`)**: MD3 token classes, lucide-react icons, theme-token-driven colors. Do not hardcode purple gradients or generic AI aesthetics — the `frontend-design` skill (AP-251 use case) is the right corrective.

---

*Snapshot date: 2026-06-11. Author: Claude (orchestrator session). Source-of-truth: the linked code files, the AGENTIRA_VISION.md (north star), and the AP project board (in-flight work). Update this PRD when the product surface changes — it's the redesign team's only ground truth.*
