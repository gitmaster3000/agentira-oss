# AgentIRA / Flowty — Pending Tasks

Captured before vacation. Pick up in priority order.

---

## 1. Profiles ↔ Agents cleanup

**Problem:** When creating an agent, the profile dropdown shows human profiles too.
That's wrong — profiles are linked to bot API keys, and now agents are linked to
profiles. The semantics are tangled.

**Decisions to make:**
- Should "agent" fully absorb the bot-profile concept? (i.e. an agent IS its
  identity; no separate `profiles` row needed for it.)
- Or: keep human profiles separate, and agents reference a *bot-only* profile
  type (filter dropdown to `role='bot'` or similar)?
- What happens to existing bot profiles + their API keys?

**Action:**
- Decide the model. Recommended: humans = `profiles`, agents = `forge_agents`,
  no cross-link via profile_id. Move any needed bot fields (API key, webhook)
  onto `forge_agents` directly.
- If keeping the FK for now, the UI dropdown must filter to bots only.
- Clean up `CreateAgentModal` accordingly.
- Migration: convert bot profiles → agent rows; archive their human-style
  profile rows.

---

## 2. Strip legacy executor/runtime fields from agent config

**Problem:** Agent config still shows:
- `executor_type` (`http` / `cli` / etc.)
- `runtime_type` dropdown (openclaw / zeroclaw / …)
- `runtime_url`, `runtime_gateway_token`, `runtime_hooks_token`,
  `runtime_agent_name`

All superseded by the new `runtime_id` FK → `forge_runtimes`.

**Action:**
- Drop the deprecated columns from `forge_agents` (Phase 8 of the original plan).
- Strip the corresponding fields from `AgentUpdate` Pydantic schema in
  `backend/forge/router.py`.
- Strip those inputs from `AgentDetail.jsx` config UI.
- `CreateAgentModal` already only shows `runtime_id` — leave that.
- `runtime_client.py` adapter: remove HTTP-gateway code paths once the UI is
  fully migrated.

---

## 3. Per-run isolated execution environment **(highest priority — first real test)**

**Goal:** When a task is assigned to an agent, the daemon should:
1. Pull the task + agent + bound runtime config.
2. Spin up an isolated workdir (`~/.agentira/workspaces/<workspace>/<task>/workdir/`).
3. Build env (`AGENTIRA_TOKEN`, `AGENTIRA_TASK_ID`, `AGENTIRA_AGENT_ID`,
   `AGENTIRA_WORKSPACE_ID`).
4. Write MCP config tmpfile from `forge_agents.config_json`.
5. Spawn the bound runtime CLI with `--mcp-config <tmp>` +
   `--output-format stream-json` (claude-specific args via
   `agentira_cli/runtimes/claude.py::build_args`).
6. Drain stream-json events and **stream them live back to the chat UI** so the
   user sees thoughts + tool calls as they happen.
7. On completion, post final usage/cost + result.

**What's already built (need to be wired together):**
- `agentira_cli/daemon/workdir.py` — workdir creation + GC.
- `agentira_cli/daemon/env.py` — env builder.
- `agentira_cli/daemon/mcp.py` — MCP tmpfile writer.
- `agentira_cli/daemon/executor.py::run_claude_stream` — async subprocess +
  stream-json drain.
- `agentira_cli/daemon/ws_client.py` — receives `task_available` frames.
- Backend `POST /api/forge/runs/{id}/events` for streaming events back.

**What's missing:**
- The wire between `ws_client.py` receiving a `task_available` frame and
  `daemon/core.py` actually dispatching to `executor.run_claude_stream`.
  Currently the WS wake-up just heartbeats.
- A queue on the daemon side that receives WS frames and drains them on the
  main loop.
- Auth model for daemon → backend event POST (daemon_id-based token? signed
  body?). Currently daemon has no auth credential.
- Concurrency: multiple runs in flight = isolated workdirs + an asyncio
  semaphore (`max_concurrent_tasks`).
- Frontend: the run detail page needs to subscribe (poll or SSE) to the
  events feed and render messages live.

**Acceptance test:**
- Create an agent bound to the local `claude` runtime.
- Assign a task. Watch the runs page. See assistant text + tool calls stream
  in real time. On completion, run shows status=completed, tokens, cost.

---

## 4. Total cost / usage accounting per runtime *(low priority)*

**Problem:** `forge_agents.total_cost_usd` was simple when one model = one
price table. Now each runtime may have its own pricing model:
- `claude` — known per-token rates from Anthropic.
- `openclaw` — wraps multiple providers; cost depends on which downstream
  model was used (returned in stream-json `result` events).
- `codex`, `gemini`, etc. — provider-specific.

**Questions:**
- Do we trust each runtime to report cost in its `result` event?
- Or compute cost in the backend from `model_used` + token counts via the
  pricing table (`forge/pricing`)?
- Per-run or per-message granularity?

**Action:** defer until a few real runs are flowing. Then look at what
`run_claude_stream` actually emits and decide.

---

## Quick state-of-the-system snapshot (so future-you remembers)

- **Daemon** = runtime host. Detects `claude` (Claude.app bundle) + `openclaw`
  (homebrew). Registers with backend via `daemon_id`. No bot identity needed.
- **Backend** runs in Docker on `:8111`. `forge_router` requires JWT;
  `forge_daemon_router` (register / heartbeat / ws) is public.
- **Frontend** runs in Docker on `:3111`. Has Forge → Runtimes tab and
  CreateAgentModal with runtime picker. Sync OpenClaw button removed.
- **Repo layout:** `agentira/` (backend, daemon CLI, compose) + sibling
  `agentira-frontend/`. Compose references `../agentira-frontend`. README
  documents the requirement.

## Files most likely to touch on return

- `backend/forge/models.py` — drop deprecated agent columns
- `backend/forge/router.py` — `AgentUpdate` schema + filter profile dropdown
- `backend/forge/services.py` — agent creation / updates
- `agentira-frontend/src/components/CreateAgentModal.jsx` — profile filter
- `agentira-frontend/src/pages/forge/AgentDetail.jsx` — strip legacy fields
- `agentira-cli/agentira_cli/daemon/core.py` — wire WS → executor
- `agentira-cli/agentira_cli/daemon/executor.py` — verify stream forwarding
