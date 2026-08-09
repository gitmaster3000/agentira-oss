# Agentira redesign → implementation map

The prototype (`Agentira.dc.html`) is **one file on purpose** — it streams and stays
directly editable for design review. This doc is the seam that makes it
**plug-and-play** for engineering: every screen in the prototype maps to a React
component in `agentira-frontend/` and the `api.js` call that feeds it. Types live in
[`agentira.types.ts`](./agentira.types.ts).

**Pattern:** each component takes a typed prop (mock today) → swap in the `api`
call when wiring real data. No component fetches inside itself except the page-level
containers listed under "loads".

---

## Shell (always mounted)

| Prototype region | React file | Loads | Types |
|---|---|---|---|
| Left sidebar + workspace header | `components/Sidebar.jsx` | `api.getProjects()`, `api.forge.getStats()` | `Project[]` |
| Project switcher dropdown | `components/Sidebar.jsx` | `api.getProjects()` | `Project[]` |
| Top bar + breadcrumb | `components/Navbar.jsx`, `components/Breadcrumbs.jsx` | — | — |
| **Bell** summary dropdown | `components/Navbar.jsx` (new `NotificationsMenu`) | `api.getNotifications(true)` | `Notification[]` |
| **Pulse** dock (live runs) | new `components/PulseDock.jsx` | `api.forge.listRuns({status:'running'})` | `Run[]` |
| Guide chat FAB | `components/FloatingChat.jsx` | `api.forge.getConcierge()` | `ChatThread` |

> **Renamed:** "Forge" → **Build Settings** everywhere. Keep the route, change the label.

---

## Studio (per-project)

| Prototype screen | React file | Loads | Types |
|---|---|---|---|
| Home cockpit | `pages/StudioDashboard.jsx` | `getProjects`, `forge.listRuns`, `getNotifications` | `Project[] · Run[] · Notification[]` |
| Project Overview | `pages/ProjectOverview.jsx` | `getProject`, `getProjectMembers`, `getProjectActivity`, `listProjectRepos` | `Project · Member[] · Epic[]` |
| **Board** + card sideview drawer | `pages/Board.jsx`, `components/TaskCard.jsx`, `components/TaskDetailPanel.jsx` | `api.getBoard(projectId)` | `BoardColumn[]` |
| Board settings panel | new `components/BoardSettingsPanel.jsx` | `api.getBoard` (columns), link → Workflow | `BoardColumn[]` |
| Backlog — List + Epics views | `pages/Backlog.jsx`, `pages/BacklogBoard.jsx` | `api.listTasks`, `api.getEpics` | `Task[] · Epic[]` |
| **Roadmap** gantt + deps | `pages/Roadmap.jsx`, `components/RoadmapView/` | `api.getRoadmap(projectId,'epic')` | `Epic[]` |
| **Workflow** editor (single pipeline home) | new `pages/Workflow.jsx` | `api.getRoles()`, `api.getBoard` | `BoardColumn[] · AgentRole[]` |
| Task / Work Item (Plan·Agent·Activity·Files) | `pages/TaskPage.jsx`, `components/TaskDetail/` | `getTask`, `getActivity`, `forge.listTaskRuns`, `listAttachments` | `Task · Run · RunEvent[]` |
| Project Settings (Basics·Workspace·Repos·Members·**Automation**·Webhooks) | `pages/ProjectSettings.jsx` | `getProject`, `listProjectRepos`, `getProjectMembers` | `Project · Member[]` |

> **Unified settings:** the old Project-Settings *Workflow / Gates / Conductor* tabs
> collapse into one **Automation** tab that links to the Workflow editor — the single
> source of truth for the pipeline. Board settings no longer duplicates rules/gates.

---

## Build (workspace-shared, project-independent)

| Prototype screen | React file | Loads | Types |
|---|---|---|---|
| Agents grid | `pages/forge/*` (Agents list) | `api.forge.listAgents()` | `Agent[]` |
| Agent Detail — **3-layer Toolset** + prompt/runtime/settings/activity | `pages/forge/*` (Agent detail) | `getAgent`, `getDispatchPreview`, `getAgentCosts` | `Agent · AgentToolset` |
| Runs list | `pages/forge/*` (Runs) | `api.forge.listRuns(params)` | `Run[]` |
| Run Detail — Summary·Conversation·Changes·Cost | `pages/forge/*` (Run detail) | `getRun`, `listRunEvents` | `Run · RunEvent[]` |
| Conductor | `pages/forge/*` (Conductor) | `api.forge.getConductor()` | `Conductor` |
| Runtimes | `pages/forge/*` (Runtimes) | `api.forge.listRuntimes()` | `Runtime[]` |
| MCP Servers | `pages/forge/*` (MCP) | `api.forge.listMcpServers()` | `McpServer[]` |
| Build Settings (pricing/models) | `pages/forge/*` (settings) | `getPricing`, `getOpenClawModels` | — |

---

## Global

| Prototype screen | React file | Loads | Types |
|---|---|---|---|
| Inbox (All·Mentions·Agents·Assigned·Workflow) | `pages/ActivityFeedPage.jsx` | `api.getNotifications(false)` | `Notification[]` |
| My Work | new `pages/MyWork.jsx` | `api.listTasks(null, …, me)` + `getNotifications` | `Task[] · Notification[]` |
| **Chat** (sidebar) — per-agent, scope dropdown | `components/FloatingChat.jsx` → promote to `pages/Chat.jsx` | `forge.listConversations`, `forge.listMessages(id,{scope_key})` | `ChatThread[] · ChatMessage[]` |
| Workspace Settings (Profile·API key·Service accounts·Notifications) | `pages/Settings.jsx` | `getMe`, `listServiceAccounts` | `Member` |

---

## Key behaviors to preserve

1. **1 task = 1 run.** The Task "Agent" tab shows the single current run inline (no
   run picker). `task.liveRunId` drives the glow + drawer "Agent working" badge.
2. **Pulse is global.** The top-bar "N running" pill and the dock read the same
   `forge.listRuns({status:'running'})` — one source, mounted in the shell.
3. **Chat scope = conversation key.** The header dropdown maps to `ChatScope`
   (`general | project | task`) → `scope_key` on `listMessages`/`createMessage`.
4. **Run summary is rolling.** `Run.summary` regenerates each turn while `status ==
   'running'`; show `summaryUpdatedAt`.
5. **One accent for run/activity.** All "running / live" states use the Pulse blue
   `#38bdf8`. Agent identity colors are separate (e.g. Planner amber).
6. **Workflow editor is the pipeline's only config home.** Board settings + the
   Automation settings tab both *link* here; they never duplicate gates/roles.

## Wiring order (suggested)

1. Drop in `agentira.types.ts`, point `api.js` returns at the interfaces.
2. Shell first: `Sidebar` + `Navbar` + `PulseDock` (live data proves the realtime path).
3. Board + TaskCard + drawer (highest-traffic surface).
4. Task page (the run-inside-task model).
5. Build section (Agents/Runs/Agent Detail) — mostly read views over `forge.*`.
6. Roadmap, Workflow editor, Settings last.
