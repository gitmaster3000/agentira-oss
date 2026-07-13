# MCP & Tools — Layering Model

Agents in Agentira run inside a host runtime (claude-code, codex, openclaw, …).
Each runtime already brings its own tools, host config, and personal MCP
servers. Agentira composes alongside — it never replaces what the host has
unless you ask it to.

This doc describes the three layers, what we touch, and how to override.

## The three layers

At dispatch time, the tools the agent sees come from three places:

### Layer 1 — Runtime built-ins (runtime-owned)

What the binary ships with. Not configurable by Agentira.

| Runtime | Built-ins |
|---|---|
| claude-code | `Read`, `Edit`, `Write`, `Bash`, `Grep`, `Glob`, `WebFetch`, `Task`, `TodoWrite`, in-process Skill loader, hooks, permission system |
| codex | its own native tool set |
| gemini-cli | its own native tool set |
| openclaw | tools on the **per-Agentira engine agent** (`ar-<agent8>`, `tools.profile=full`) |
| ollama (bare gateway) | none — pure token generation |

These appear on every dispatch automatically because the runtime is the
executor.

### Layer 2 — User's host config (user-owned)

Whatever the user has installed in their own environment. Agentira reads
none of this and writes none of this.

| Runtime | Host config sources |
|---|---|
| claude-code | `~/.claude.json` (personal MCP servers), `~/.claude/CLAUDE.md`, `~/.claude/plugins/`, `~/.claude/skills/`, `~/.claude/settings.json` |
| codex | `~/.codex/` |
| gemini-cli | `~/.gemini/` |
| openclaw | `~/.openclaw/openclaw.json` — we create **engine agents** `ar-<id>` (empty system override, full tools, workspace = Agentira desk). We do **not** run product turns as personal `main`. See [openclaw-engine-agents.md](./openclaw-engine-agents.md). |

**We deliberately do not pass `--strict-mcp-config` by default** for
claude-code. Without that flag, claude-code merges the user's host MCP
servers with our per-task additions, so user-installed integrations
(personal Slack, GitHub, Linear, etc.) keep working inside Agentira-dispatched
runs.

### Layer 3 — Agentira's per-dispatch additions (what we own)

Per-agent, per-call, ephemeral. Written to a tempfile and passed as
`--mcp-config <path>` (claude/codex/gemini) or merged into the request body
(gateway runtimes). Contents:

- **`agentira`** MCP (always, auto-injected) — `list_tasks`, `get_task`,
  `add_comment`, `finish_run`, `get_me`, `get_my_involvement`, …
  Authenticated with the agent's own API key, so tool calls attribute to
  the agent in the audit log.
- **`memory`** MCP (always, auto-injected) — per-(agent, project) knowledge
  graph. `MEMORY_FILE_PATH` is scoped under `~/.agentira/memory/<agent>/<project>/memory.json`.
- **Opt-in servers** (e.g. `filesystem`) — toggled per-agent in the
  Toolset picker.

Plus `--append-system-prompt "<awareness preamble>\n---\n<persona>"`,
which composes additively with the user's host `CLAUDE.md`.

You can inspect the exact resolved JSON for an agent in **Forge → Agent →
Config → Toolset → mcp-config.json**. Bearer tokens and secret-shaped env
vars (`*TOKEN*`, `*KEY*`, `*SECRET*`, `*PASSWORD*`) are redacted in that
viewer.

## How merging works at runtime

When claude-code starts, it loads in this order:

1. Built-in tools (Layer 1).
2. Reads `~/.claude.json`'s `mcpServers` (Layer 2 — host).
3. Reads `--mcp-config` tempfile (Layer 3 — ours).
4. Unions them. Name collisions resolve last-write-wins. Our server names
   (`agentira`, `memory`) are deliberately unique to avoid shadowing user
   servers.

System prompt assembly:

1. Built-in runtime system prompt (immutable).
2. Host `CLAUDE.md` content.
3. `--append-system-prompt "<awareness preamble>\n---\n<persona>"` (ours, appended).

The awareness preamble is auto-baked from agent identity, current screen
context (project / task from `user_context`), and recent run history. The
persona comes from the agent's `system_prompt` field.

## Override: strict mode (per agent)

There are environments where merging host MCP is wrong:

- A locked-down deploy where only Agentira-blessed tools may run inside an
  agent.
- A user with a personal MCP server that mustn't fire inside automated
  agent runs (writes to personal accounts, etc.).
- Reproducibility: you want the same tool surface across every run,
  regardless of who's logged in on the daemon host.

For those cases the agent's profile carries a `mcp_strict` flag (column
`profiles.mcp_strict`, defaults to `false`). When true:

- claude-code dispatches add `--strict-mcp-config` → host `mcpServers` are
  ignored; only the Agentira-resolved JSON is in scope.
- Layer 1 (built-in tools) is unaffected — strict mode applies to MCP, not
  to built-in Read/Edit/Bash etc. Those still work.
- Layer 2's CLAUDE.md / skills / hooks are also unaffected. Strict mode is
  scoped narrowly to MCP server merging.

The flag is plumbed end-to-end (Profile → dispatch frame → daemon →
`runtime_cls.build_args`) but isn't yet exposed in the UI. Toggle it via
the REST `PATCH /api/forge/agents/{id}` endpoint or directly in the DB
until the picker lands.

To go fully isolated (no MCP at all), set `mcp_strict=true` AND clear
`mcp_servers`; the agentira and memory servers are still auto-injected by
the registry, so the agent will get exactly those two and nothing else.

## What this means concretely

- **User installs Slack MCP locally** → their Agentira agent automatically
  gets Slack tools when dispatched. We didn't configure that; they did once
  for personal claude-code use, and we don't strip it.
- **User has `~/.claude/CLAUDE.md` saying "always run `bun test` before
  committing"** → Agentira agents follow it too. The agent's persona is
  appended after.
- **Agent toggled to use `filesystem` in Toolset** → gets that one server
  PLUS all the user's host servers PLUS `agentira` + `memory`.
- **OpenClaw host plugins / tools** → available when the engine agent's
  tools profile allows them. Persona still comes only from Agentira.

## Fragile spots

1. **Host MCP that needs interactive auth on first use** — claude-code will
   prompt; in a non-tty daemon spawn that hangs. The preflight probe in
   `executor.py` catches unreachable but not interactive-auth states.
2. **Name collisions** — if a user names a host MCP server `agentira` or
   `memory`, ours wins by virtue of being last in the merge. Renaming
   would silently shadow theirs.
3. **OpenClaw bootstrap content drift** — if someone edits an engine agent
   (`ar-*`) and adds SOUL/bootstrap persona content, it can fight Agentira's
   system message. We set empty `systemPromptOverride` + `skipBootstrap` on
   ensure; re-apply is idempotent. Do not point product runs at personal
   `main`.
4. **Per-runtime adapter coverage** — only `claude.py` is fully wired for
   `--strict-mcp-config`. codex/gemini adapters will need the same flag
   when added.

## Deployment guide for `AGENTIRA_MCP_URL`

The URL baked into the agent's MCP config has to be reachable from
wherever the daemon runs the runtime subprocess.

| Deploy shape | Daemon runs on | What `AGENTIRA_MCP_URL` should be |
|---|---|---|
| Local dev | your host | `http://localhost:8000/mcp` (default) |
| Self-hosted | user's machine | `https://mcp.yourdomain.com/mcp` (public HTTPS) |
| Hosted SaaS, hosted daemon | a cluster container | service-internal DNS, e.g. `http://mcp.svc.cluster.local:8000/mcp` |

Set the env var on the **backend** container (the URL is baked into the
config by the backend; the daemon receives the resolved JSON and forwards
it as a tempfile).

When the daemon detects a connection-level failure to a configured MCP
URL, it logs a warning AND emits a synthetic `TextEvent` into the run
timeline so the user sees what broke instead of debugging blind.
