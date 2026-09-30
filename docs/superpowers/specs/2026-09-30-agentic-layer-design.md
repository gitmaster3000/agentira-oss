# Agentira → agentic layer: always-on AI employees (Dots/Muse parity, no model lock-in)

## Context

Agentira today is a task board + a run engine. Its agents have no personality, the
agent UI (`/forge/agents`, a 2,546-line `AgentDetail.jsx` with 7 tabs) is cumbersome, every
chat turn spawns a `claude -p` subprocess (slow, polled every 3s, no streaming) and the
agents only do software work.

In September 2026 OpenAI shipped **Dots** and Meta shipped **Muse / Meta Enterprise**. Their
agents are always-on, each has its own computer you can watch live, they learn preferences
and work proactively, you reach them by chat, voice, Slack or Teams, risky actions need
approval, and they connect to thousands of apps. The user is pivoting Agentira to that
product: an **agentic layer that humans and AI work through together**, model-agnostic,
self-hosted on the customer's own AWS/GCP or local Docker. The board stays and runs stay as
tracking, but **agents must work naturally**. First customer: the user, running their own
website and org on it.

Decisions made in this session:
- Keep Agentira's Python control plane and borrow Paperclip's ideas (org chart, budgets,
  heartbeat wakeup queue, goal ancestry). Do not adopt Paperclip's code.
- Harness: **OpenWorker** (Andrew Ng, MIT, Python, any model via `aisuite`, 25+ connectors,
  risk-tier approvals) is the **only** agent harness.
- The existing CLI runtimes (claude, codex, gemini, grok, opencode, openclaw) **stop being
  agent runtimes**. Driving agents with command-line calls is too weak. Each CLI survives
  only as a **subscription model bridge** inside the harness's model layer: an aisuite
  provider (`claude-subscription`, `codex-subscription`) that calls the CLI with its own
  tools disabled, just to get completions.
- That lets any agent run on a ChatGPT or Claude subscription instead of API-tier billing.
  API keys and Ollama remain ordinary aisuite providers.
- Assumption: the user's "openharness adapter" means this harness layer.
- Isolation: one **NVIDIA OpenShell** sandbox per agent (the agent's own computer), many
  sandboxes per host.
- Milestone 1: hosts run on **local Docker**. AWS/GCP come later.
- Voice: **ElevenLabs** with any model behind it. The Conductor is the **chief of staff**:
  it hears the user and routes to the right employee.
- Every human in the org can work with every agent (human-AI collaboration), not just the
  owner.
- Agent-to-agent (A2A): not settled by the user, so the design below chooses it (visible
  delegation rooms first, the Google A2A protocol as a later adapter).
- Full redesign of the agent UI.

Standing rules (from memory) that apply throughout:
- Work on `main-rsi`, local stack only.
- Merge only through PRs.
- Engine stays project-agnostic.
- Workflow policy and prompts are config (YAML/markdown), never Python constants.
- New code uses the repo layer, has TDD tests on Postgres, and plain-language UI.
- Track the work on the local Agentira board.

## Target architecture

```
Humans (web · mobile · voice · Slack/Teams/email later)
        │
Agentira control plane  (existing FastAPI + Postgres, backend/)
  identity/org · board · runs & audit · approvals inbox · chat hub (WS streaming)
  chief-of-staff router · wakeup queue + budgets · fleet registry · voice bridge
        │  (hosts dial OUT over WS — no inbound ports on customer infra)
Agent host  = agentira-cli daemon, extended ("agentira-host")
  runs on: laptop Docker (M1) │ customer AWS VM │ customer GCP VM
  manages N sandboxes, relays events / heartbeats / live-desktop stream
        │
Agent computer = OpenShell sandbox per employee (persistent volume)
  harness: OpenWorker server (only harness)
  model layer (aisuite): API providers · Ollama · subscription bridges (claude/codex CLI, tools off)
  desktop: Xvfb + browser + noVNC for live peek · policy: default-deny, allowlisted hosts
```

Model-agnostic:
- Each agent's harness calls whatever model is configured (OpenWorker/aisuite, or the CLI's
  provider).
- Keys live encrypted in the control plane and are injected into the sandbox env. Reuse the
  deploy-token encryption.
- The OpenShell network policy allowlists only the provider hosts the agent needs.

## Build on what exists (do not rebuild)

- **Identity.** `Profile` (`backend/models.py:154`) already has `avatar_url`, `personality`,
  `model`, `system_prompt`, `runtime_id`, `env_vars` and `is_system`. Add persona, org and
  budget fields here. Per `CLAUDE.md`, Profile stays Profile.
- **Daemon.**
  - The WS dial-out and heartbeat already exist (`backend/forge/ws_dispatch.py:34,576`,
    `/daemon/ws` in `router.py:1005`).
  - The runtime registry (`agentira-cli/agentira_cli/runtimes/registry.py`) and the adapter
    contract (`runtimes/base.py` `Capability`) also exist.
  - Add a sandbox manager and an OpenWorker control client. No new transport.
  - The CLI runtime adapters (`runtimes/claude.py`, `codex.py`, …) are retired as agent
    runtimes. Their auth and invocation know-how moves into the subscription model bridges.
    The rest is deleted once parity lands. Old runs stay readable.
- **Chat.** `AgentMessage` / `Conversation` plus `conversation_scope_key`
  (`backend/forge/services.py:183`, documented as the single extension point). Add scopes
  `dm:<human_id>` and `room:<room_id>`. Replace polling with a push channel alongside
  `ClientHub` (`ws_dispatch.py:354`).
- **Conductor.** `backend/forge/conductor.py` (turns, `send_runtime_message`), prompts in
  `templates/conductor/*.md`, scheduler in `backend/forge/scheduler.py` (APScheduler). The
  chief-of-staff routing prompt goes in the templates.
- **Guide.** `backend/forge/concierge.py` is the existing floating-chat guide. It merges into
  the chief of staff, and its UI (`FloatingChat.jsx`) becomes the global talk button.
- **Role templates.** `templates/agents/*.yaml|md` are seeded set-if-empty by
  `backend/agent_templates.py`. Add business roles and persona blocks here.
- **Runs.** `Run` (`backend/forge/models.py:180`) plus the workflow driver. Harness work
  keeps being recorded as runs, so it is tracked on the board.
- **Pattern to follow for a new domain:** `docs-oss/docs/contributing/adding-a-feature.md`
  (gateway → handler → repo → adapter), using the deploy feature as the reference.

## Phases

Each phase ships something usable and gets its own spec in `docs/superpowers/specs/` and its
own plan via writing-plans.

### P0 — Spike: OpenWorker headless in OpenShell (throwaway, 2–3 days)
Prove each of these in a container on the laptop:
1. OpenWorker server mode is driven only through its token API (`X-OpenWorker-Token`), with
   no Tauri shell.
2. Session and turn events can be streamed.
3. Approval requests can be intercepted and answered programmatically.
4. The model can be set per agent, including Ollama.
5. It runs under OpenShell with an allowlist.
6. An Xvfb + noVNC desktop is visible from outside.
7. **Subscription bridge.** An aisuite provider wrapping `claude -p --output-format
   stream-json` with built-in tools disabled, and `codex exec`, can drive OpenWorker's
   tool-calling loop. Tool calls go through a JSON protocol in the prompt when the CLI has no
   native function-calling passthrough. Measure latency and tool-call reliability. Check
   each provider's subscription terms for automated use and flag the risk to the user.

Output: go/no-go plus notes on its API. If the API falls short, fork it (MIT) and add a thin
HTTP/WS control API. If the subscription bridge is unreliable, ship API keys and Ollama
first and treat the bridge as best-effort.

### P1 — Agent computers + fleet (local Docker)
- **Image.** `agentira-computer`: OpenShell sandbox base, OpenWorker server, Xvfb, browser,
  noVNC, a small bridge process, and a persistent volume per agent (memory and files survive
  restarts).
- **Host daemon.** A sandbox manager (create, start, stop, restart, destroy via the Docker
  API) and an OpenWorker control client. Subscription bridges ship inside the image; the
  user logs in once with `claude login` / `codex login` on the host, and the credentials are
  mounted read-only. Existing dev agents migrate to OpenWorker, coding through its terminal,
  file and git tools. Heartbeat frames carry per-sandbox state
  (`starting|idle|working|waiting_on_human|error|stopped`) plus CPU, memory and disk.
- **Control plane.**
  - New tables `agent_hosts` and `agent_computers`, each with its own repo module.
  - A liveness reconciler: a missed heartbeat marks the computer stale, then triggers an
    auto-restart with a budget of attempts, then escalates to the Inbox.
  - Host enrollment tokens.
- **Live peek.** The host relays the noVNC stream over its outbound WS to the control plane,
  which serves it to the browser with an auth check per viewer. A run/step timeline sits
  alongside.
- **Done when:** you can hire an agent, it starts its own computer in Docker, the Fleet page
  shows its heartbeat, you watch its desktop live, and killing the container auto-recovers.

### P2 — Interaction layer + UI redesign (see UI section)
- **Streaming chat hub.**
  - A WS per viewer carrying message, token and tool-step events.
  - Multi-human: each human has their own DM with each employee (`dm:<human_id>`), and
    employees are shared teammates.
  - The chief of staff is the default recipient.
- **Chief-of-staff router.** It answers itself or hands off. The handoff shows as a card in
  the chat ("Handing to Maya (Marketing)"), after which the user is talking to Maya. The
  routing policy lives in the YAML/prompt templates.
- **Approvals Inbox.** OpenWorker risk-tier escalations, workflow gates and agent questions
  go into one inbox. Approving or rejecting in the UI sends the decision back down to the
  sandbox.
- **Personas.** Name, avatar character, voice id, tagline, greeting, personality and role
  live on `Profile`. Templates ship with them. Role templates cover the existing dev roles
  plus Researcher, Content/Marketing, Support and Ops/Admin (business roles use OpenWorker
  connectors: Gmail, Calendar, Slack, Notion, GitHub…).
- **Done when:** you run your website/org by chatting with employees who stream replies in
  well under a second to first token, show their work live, ask approval in the Inbox, and
  record long work as runs on the board.

### P3 — Company OS (Paperclip ideas, ported into Agentira)
- **Org chart.** `Profile.reports_to_id`; goals with ancestry linked to epics.
- **Budgets.**
  - A monthly cost cap per agent. OpenWorker and the runtimes emit cost events.
  - A hard stop blocks wakeups and shows a notice in the Inbox.
  - A soft threshold sends a warning.
- **Wakeup queue.** A DB-backed queue that wakes agents on schedule (proactive heartbeat) or
  on events (message, assignment, @mention). Each wake does an atomic checkout, runs a
  budget check, then resumes context. Proactive mode is read-only by default (the Dots rule).
- **Learning.** A feedback thumbs up/down on replies and results writes to the agent's
  memory: OpenWorker memory plus an org-level "brain" notes table readable by all employees.

### P4 — Voice + animated avatars
- **ElevenLabs.**
  - Each employee is one ElevenLabs agent with its own voice.
  - Its Custom LLM URL is a control-plane endpoint,
    `POST /v1/voice/{profile_id}/chat/completions`, which is OpenAI-compatible and returns
    SSE.
  - That endpoint streams from a fast "presence" turn (the employee's persona, context and
    model via LiteLLM). Tools on it can delegate long work to the employee's computer and
    query the board.
  - Routing between employees uses ElevenLabs agent transfer.
- **Avatars.**
  - Animated 2D characters built as a parametric layered SVG rig: skin, hair, outfit,
    accessory, colour.
  - Their states are idle, listening, thinking, talking and working.
  - The mouth is driven by the output volume of the ElevenLabs React SDK. A Rive upgrade can
    come later.
- **Call UI.** A floating call pill that works on every screen, plus a full-screen call view
  with the live-peek panel.

### P5 — A2A + channels
- **Visible delegation rooms** (the chosen design for A2A).
  - `room:<id>` threads where employees call `ask_colleague` (a quick synchronous question)
    or `hand_off_work`, which creates a board task and a run.
  - Humans can watch or join, and group rooms (standup, brainstorm) are possible.
  - The message shape mirrors the Google A2A protocol (Task, Message, Part, Artifact,
    AgentCard), so the external adapter stays thin.
- **Channels.** Slack/Teams bots and a per-agent email address feed the same chat hub, so
  context follows the agent across channels.

### P6 — Customer cloud hosts
- A Terraform module for AWS (EC2) and GCP (GCE): a VM with Docker and `agentira-host`,
  enrolled with a token and connecting out only.
- The control plane needs no cloud credentials.
- The Fleet page gets an "Add host" wizard with three choices: this laptop, AWS or GCP.

### P7 — External A2A protocol
- Publish an AgentCard per employee at `/.well-known/agent.json`.
- Add an A2A task endpoint so outside agents can hire employees, and an A2A client so
  employees can call external agents.

## UI redesign (P2 core, extended in P3–P5)

Principle: talk to people, don't configure machines. Plain language by default, with an
"Advanced" reveal for internals (runtime, harness, host, model ids). The frontend stays
React 19 + Vite + Tailwind + tokens. Use the `frontend-design` skill and dispatch to
Agentira's frontend-implementer agent.

**Navigation** (the board keeps its current place): **Team · Inbox · Board · Rooms · Org ·
Fleet (admin)**. A global "Talk" button or voice pill is always available, and it reaches
the chief of staff.

- **Team (new home for agents; replaces `/forge/agents`).**
  - A grid of employee cards, each with an animated avatar, name and role.
  - Each card shows its live state in words ("Writing launch post · 12m", "Waiting on you",
    "Idle — researching competitors").
  - Each card has three buttons: Chat, Call, Peek.
  - A "Hire" button sits at the top.
  - The old dashboard stays reachable as "Advanced view", not deleted.
- **Employee space (replaces the 7-tab `AgentDetail`).** A two-pane layout.
  - **Left: conversation.** Streaming chat with tool steps collapsed into friendly lines.
    Approval cards, task and run cards, and handoff cards appear inline. A composer with
    attachments and a mic.
  - **Right: "Their computer".**
    - A live desktop (noVNC).
    - A "Now doing" step timeline.
    - The work queue: tasks from the board, runs and schedules.
    - Tabs: Desktop, Activity and Files.
  - Header: avatar, status, "Pause", "Stop", "Call" and settings (gear).
- **Settings drawer (replaces `ConfigTab`).** Four plain sections.
  1. **Profile:** look (avatar builder), voice (ElevenLabs picker with preview), name,
     personality sliders plus free text, greeting.
  2. **Job:** role, reports to, goals, working hours and proactive mode, schedules.
  3. **Access:** connected apps, what needs approval (risk-tier toggles), monthly budget,
     who can talk to them.
  4. **Brain:** model, and how it is paid for ("My Claude subscription", "My ChatGPT
     subscription", "API key", "Local model"). Behind Advanced: computer location, system
     prompt, MCP, env.

  Autosave, with an undo toast on each change.
- **Hire flow (about 30 seconds).** Pick a role template, then pick a look and voice, then
  connect apps, then set a budget. They are hired, their computer boots, and they greet you.
- **Inbox.** Everything that needs a human, across all employees: approvals, questions,
  budget stops, failures and daily summaries. One-tap approve or reject, with context.
- **Org.** Reporting lines with drag to re-parent. Goals roll up.
- **Rooms.** A2A and group threads, readable by humans who can join them.
- **Fleet (admin).** Hosts and computers with their heartbeats, resources, restart and logs.
  "Add host" lives here.

Old pages (`AgentsDashboard.jsx`, `AgentDetail.jsx`, `Chat.jsx`, `FloatingChat.jsx`) stay
behind the Advanced route until parity, then retire.

## Critical files

- **Backend (edit):**
  - `backend/models.py` (Profile persona/org/budget fields)
  - `backend/forge/models.py` (hosts, computers, wakeups, approvals, cost events)
  - `backend/forge/services.py` (`conversation_scope_key`, `send_runtime_message` routing)
  - `backend/forge/ws_dispatch.py` (host heartbeat payload, viewer chat WS)
  - `backend/forge/conductor.py` + `templates/conductor/*.md` (chief of staff)
  - `backend/forge/concierge.py` (fold into chief of staff)
  - `backend/forge/scheduler.py` (wakeups)
  - `backend/agent_templates.py` + `templates/agents/*` (roles and personas)
- **Backend (new, one domain per module + a repo each):**
  - `backend/forge/fleet.py`
  - `backend/forge/approvals.py`
  - `backend/forge/wakeups.py`
  - `backend/forge/budgets.py`
  - `backend/forge/voice.py`
  - `backend/forge/rooms.py`
  - `backend/forge/repos/*`
- **Daemon:**
  - `agentira-cli/agentira_cli/openworker_client.py` (new)
  - `runtimes/*` (retired as agent runtimes, deleted after parity)
- **Subscription bridges** (in the image):
  - `images/agentira-computer/bridges/claude_subscription.py`
  - `images/agentira-computer/bridges/codex_subscription.py`
  - Both are aisuite providers.
  - `daemon/sandboxes.py` (new, Docker/OpenShell manager)
  - `daemon/ws_client.py` (heartbeat and stream relay)
- **Image:** `images/agentira-computer/` (new Dockerfile plus OpenShell policy).
- **Frontend:**
  - `frontend/src/routes.js` and `App.jsx`
  - New pages: `pages/team/*`, `pages/inbox/*`, `pages/org/*`, `pages/fleet/*`,
    `pages/rooms/*`
  - New components: `components/avatar/*`, `components/voice/*`
  - `api.js` (new `api.team`, `api.fleet`, `api.inbox`) and a WS client hook
- **Docs:** spec per phase, an ADR for host/sandbox architecture, an ADR for the chat WS
  replacing polling, and `docs-oss` updates.

## Process

1. After approval, write the program spec
   `docs/superpowers/specs/2026-09-30-agentic-layer-design.md` on `main-rsi`. It holds this
   design plus the P0 spike questions.
2. Run P0 myself as a throwaway spike and report go or no-go.
3. For each phase from P1 on:
   - Write the spec, then the writing-plans plan.
   - Put an epic and its tasks on the local Agentira board. The MCP is currently
     disconnected because the local stack is down, so it needs a restart.
   - Dispatch to Agentira agents as Conductor and verify their work.
   - Merge only through a PR.

## Verification

- **P0:** a scripted demo. `docker run` the computer image, then drive one OpenWorker task by
  API with (a) Claude and (b) Ollama. Capture an approval event, answer it, and see the
  noVNC desktop in a browser.
- **P1:**
  - Backend pytest on Postgres covering the host/computer repos, the heartbeat state machine
    and the stale-computer reconciler.
  - Daemon unit tests for the sandbox manager against real Docker.
  - Manual: hire an agent, confirm the Fleet page is green, `docker kill` the sandbox and
    watch it auto-restart, then check the heartbeat and Inbox entries.
- **P2:**
  - pytest for scope keys, the router handoff and approvals round-trip.
  - Vitest for the chat WS hook and components.
  - `cd frontend && npx vite build`.
  - End-to-end in the in-app browser against the local stack (127.0.0.1:3113): talk to the
    chief of staff, get handed to an employee, approve an action, and see the run on the
    board.
  - Check the time to first token.
- **P3 onward:**
  - Budget hard-stop test, wakeup idempotency (atomic checkout) test, and a proactive
    read-only enforcement test.
  - A voice call test through ElevenLabs, with latency logged.
  - A room delegation creates a task and a run.
  - Terraform `plan` and `apply` on a sandbox AWS account in P6.
