---
id: configuration
title: Configuration reference
sidebar_label: Configuration
---

# Configuration reference

Development requires no `.env` file. `docker-compose.override.yml` sets development values directly, because development credentials are not secrets.

QA and production require explicit configuration. Copy `.env.qa.example` or `.env.prod.example` and complete it. The Compose files refuse to start when required values are missing.

## Required for QA and production

| Variable | Purpose |
|---|---|
| `JWT_SECRET` | Signing secret. Generate with `openssl rand -hex 32`. |
| `POSTGRES_PASSWORD` | Database password |

## Backend

| Variable | Purpose |
|---|---|
| `AGENTIRA_ENV` | Environment name. `dev` enables development-only paths. |
| `AGENTIRA_DB_URL` | Database address |
| `AGENTIRA_APP_DB_URL` | Application database address, when separated |
| `AGENTIRA_DB_ADMIN_URL` | Administrative database address for migrations |
| `AGENTIRA_ATTACHMENTS_DIR` | Attachment storage path. Must be a persistent volume. |
| `AGENTIRA_PUBLIC_URL` | Public address of the backend |
| `AGENTIRA_MCP_URL` | MCP server address given to agents |
| `FRONTEND_URL` | Public frontend address. **Required for `agentira daemon login`.** |
| `APP_BASE_URL` | Base address for generated links |
| `CORS_ALLOW_ORIGINS` | Permitted browser origins |
| `AGENTIRA_ADMIN_PASSWORD` | Bootstrap administrator password |

:::warning
Without `FRONTEND_URL`, `agentira daemon login` fails with "didn't return a usable verification URL". This is the most common deployment mistake.
:::

## Authentication

| Variable | Purpose |
|---|---|
| `GITHUB_CLIENT_ID` | GitHub OAuth |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth |
| `GOOGLE_CLIENT_ID` | Google OAuth |
| `GITHUB_WEBHOOK_SECRET` | Verifies inbound GitHub webhooks |
| `AGENTIRA_GITHUB_APP_ID` | GitHub App used by evidence providers |

Evidence providers need GitHub App credentials. Without them, `github_pr`, `ci`, and `commit` answer `unknown` and block. See [Gates and evidence](./gates-and-evidence.md).

## MCP server

| Variable | Purpose |
|---|---|
| `MCP_HOST` | Bind address |
| `MCP_PORT` | Bind port |

## Dispatch and WebSocket

| Variable | Purpose |
|---|---|
| `FORGE_WS_HEARTBEAT_INTERVAL_S` | Heartbeat interval |
| `FORGE_WS_HEARTBEAT_TIMEOUT_S` | Heartbeat timeout |
| `FORGE_OUTBOX_SWEEP_INTERVAL_S` | Outbox redelivery sweep interval |
| `FORGE_DISPATCH_REDELIVER_TTL_S` | How long an unacknowledged dispatch stays eligible |
| `FORGE_LIMIT_FIRST_BACKOFF_S` | Usage limit with no reset time: wait this long first (default 1800) |
| `FORGE_LIMIT_BACKOFF_S` | Usage limit with no reset time: wait after each further hit (default 3600) |
| `FORGE_LIMIT_RESET_GRACE_S` | Added to a parsed reset time before resuming (default 60) |
| `FORGE_LIMIT_MAX_PAUSES` | Consecutive limit pauses before the run fails for real (default 48) |
| `FORGE_RESTART_MAX_RESUMES` | Times the reconciler relaunches a run (same session) after its daemon/backend restarted, before failing and notifying admins (default 3) |

An agent may set `{"fallback_model": "<id>"}` in its `config_json`; a run that hits a usage limit then resumes at once on that model (same runtime). None by default.

## Daemon

| Variable | Purpose |
|---|---|
| `AGENTIRA_DAEMON_API_URL` | Backend address |
| `AGENTIRA_DAEMON_API_KEY` | Static key. Development only. |
| `AGENTIRA_DAEMON_NOTIFICATION_MODE` | `hybrid`, `webhook`, or `poll` |
| `AGENTIRA_DAEMON_DRY_RUN` | Accept dispatches without executing |

## Injected into agents at dispatch

Set by Agentira, not by you.

| Variable | Contents |
|---|---|
| `AGENTIRA_API_KEY` | The agent's key |
| `AGENTIRA_API_BASE_URL` | Backend address |
| `AGENTIRA_MCP_URL` | MCP server address |
| `AGENTIRA_AGENT_ID` | Agent identifier |
| `AGENTIRA_AGENT_NAME` | Agent name |

## Runtime paths

| Variable | Purpose |
|---|---|
| `AGENTIRA_CLAUDE_PATH` | Claude CLI binary |
| `AGENTIRA_CLAUDE_MODELS` | Advertised model list |
| `AGENTIRA_CODEX_PATH` | Codex binary |
| `AGENTIRA_CODEX_MODELS` | Advertised model list |
| `AGENTIRA_GEMINI_PATH` | Gemini binary |
| `AGENTIRA_GATEWAY_TIMEOUT` | HTTP gateway runtime timeout |

## Development only

These are gated on `AGENTIRA_ENV=dev` and do nothing elsewhere.

| Variable | Purpose |
|---|---|
| `AGENTIRA_DEV_MODE` | Enable development behaviour |
| `AGENTIRA_DEV_API_KEY` | Static key accepted on REST and the daemon WebSocket |
| `AGENTIRA_DEV_PROFILE` | Profile the development key maps to |

## Email

| Variable | Purpose |
|---|---|
| `SMTP_HOST` | Mail server |
| `SMTP_FROM` | Sender address |
