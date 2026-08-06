# Self-hosting Agentira

Everything Agentira needs, you run. There is no maintainer-operated service in the
loop: no license server, no telemetry endpoint, no hosted gateway your agents route
through. Clone it, boot it, and it is yours.

This guide is provider-agnostic. For a click-by-click Railway walkthrough see
[deployment.md](deployment.md); for the first-time-user tour of the product itself see
[getting-started.md](getting-started.md).

---

## What you are actually running

Two halves, and the split matters:

**The server half** — backend (FastAPI), MCP server, frontend (React behind nginx),
and Postgres. These run in Docker, on your laptop or on a server. They hold the board,
the tasks, the runs, and the audit trail.

**The machine half** — the daemon and a coding runtime. These run on *your own box*,
because that is where your code is. The daemon receives dispatch frames over a
WebSocket, spawns the runtime (the `claude` CLI, OpenClaw, Codex, a local Ollama),
owns the git worktrees, and streams events back.

```
your server (Docker)                    your machine
┌──────────────────────────┐            ┌──────────────────────┐
│ frontend · backend · mcp │◄──── WS ───┤ daemon               │
│ postgres                 │            │  └─ runtime → your   │
└──────────────────────────┘            │      git repos       │
                                        └──────────────────────┘
```

You can put both halves on the same laptop. Most people should, to start.

## Requirements

| | |
|---|---|
| Server half | Docker + Docker Compose. ~2 GB RAM is comfortable. |
| Machine half | Python 3.11+, git, and at least one coding runtime on `PATH` |
| Runtimes | [`claude` CLI](https://github.com/anthropics/claude-code), OpenClaw, Codex, or Ollama — whichever you already pay for or run locally |

The runtime is where model costs land. Agentira itself costs nothing to run and never
sees your model API keys — the daemon spawns your runtime with your existing config.

---

## 1. Boot the stack

```bash
git clone <your-fork-or-this-repo> agentira
cd agentira
docker compose up -d
```

Dev needs no `.env`: `docker-compose.override.yml` hardcodes dev values deliberately,
because dev credentials aren't secrets. Four services come up:

| Service | Address | Notes |
|---|---|---|
| frontend | http://localhost:3111 | Vite dev server with hot reload |
| backend | http://localhost:8111 | FastAPI |
| mcp | http://localhost:8000 | MCP server — agents connect here, not to the backend |
| postgres | localhost:5432 | Postgres 16, same engine as production |

Check it:

```bash
docker compose ps                                  # all four Up, postgres healthy
curl -fsS http://localhost:8111/api/auth/config    # 200
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:3111/   # 200
```

An unauthenticated `GET http://localhost:8000/mcp` returning **401 is correct** — the
MCP server requires a key.

## 2. Sign in and invite people

Sign in at http://localhost:3111 as `admin` / `admin123`. **Change that password
immediately** if the instance is reachable by anyone but you.

Seven agents are seeded on first boot: Conductor, Planner, Backend Implementer,
Frontend Implementer, Reviewer, DevOps, and the Agentira Guide.

**Signup is invite-only by design.** There is no open registration form — a stranger
who finds your instance cannot create an account. To add someone:

```bash
# New person, their own org, they become its admin
python scripts/create_invite.py --role admin

# New person joining your existing org
python scripts/create_invite.py --role member --org <org_id>
```

The script prints an invite link. It needs `AGENTIRA_DB_URL` and `FRONTEND_URL` in the
environment when run outside the container.

## 3. Connect the daemon

```bash
pip install -e agentira-cli/
agentira daemon login --api-url http://localhost:8111
agentira daemon start
```

`agentira daemon` on its own is a command group, not a command — `login` then `start`.
`login` opens a browser to the `/cli-auth` page where you approve the daemon as an
admin; the token is stored in `~/.agentira/credentials.json` with mode 0600.

Confirm:

```bash
agentira daemon status
agentira daemon logs        # want: "WS connected + registered"
```

Then check the UI — your runtimes should show **online** with a heartbeat. If they
registered but stay offline, the WebSocket did not authenticate; see Troubleshooting.

### Local shortcut, no browser

For a purely local stack the dev compose profile ships a static daemon key:

```bash
AGENTIRA_DAEMON_API_URL=http://127.0.0.1:8111 \
AGENTIRA_DAEMON_API_KEY=dev-daemon-key-local-only \
  agentira daemon start
```

This is gated on `AGENTIRA_ENV=dev` in the backend and is inert in any other
environment — the default is `prod`, so it fails safe. Never set `AGENTIRA_ENV=dev` on
a public instance.

### Running a second, isolated daemon

`AGENTIRA_HOME` redirects the daemon's pid file, credentials, logs, and workspaces:

```bash
AGENTIRA_HOME=~/.agentira-test agentira daemon start
```

**Known limitation:** agent workspaces are *not* redirected — they always land in
`~/.agentira/agents/<id>/home` regardless of `AGENTIRA_HOME`. Two daemons can coexist,
but they share agent working directories. Fix pending.

## 4. Point an MCP client at it

Any MCP-aware client (Claude Desktop, Cursor, Claude Code) can use the workspace:

```json
{
  "mcpServers": {
    "agentira": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": { "Authorization": "Bearer YOUR_AGENTIRA_API_KEY" }
    }
  }
}
```

Mint the key at **avatar → Settings → API key**. Every tool call is RBAC-checked
against that key's profile.

---

## Running it on a server

Same compose files, different override. The base `docker-compose.yml` cannot run
alone — it needs an environment override:

```bash
cp .env.example .env
# fill in JWT_SECRET (openssl rand -hex 32) and POSTGRES_PASSWORD

docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env up -d
```

### Environment variables that matter

| Variable | Where | Why |
|---|---|---|
| `JWT_SECRET` | backend, mcp | Must be **identical** on both. 32-byte hex. Rotating it logs everyone out. |
| `POSTGRES_PASSWORD` | postgres, backend | |
| `AGENTIRA_DB_URL` | backend, mcp | Full Postgres URL. Both services must point at the same database. |
| `AGENTIRA_ADMIN_PASSWORD` | backend | **Required in production.** Without it no admin is seeded and, since signup is invite-only, the workspace has no way in. |
| `FRONTEND_URL` | backend | Your public frontend address. `agentira daemon login` builds the browser approval link from it — omit it and daemon login fails with "didn't return a usable verification URL". |
| `API_UPSTREAM`, `API_HOST` | frontend | Where the nginx SPA proxies `/api`. Default to the compose `backend` service; override when the backend is elsewhere. |
| `FRONTEND_PORT` | frontend | Public port, default 80. |
| `GOOGLE_CLIENT_ID`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | backend | Optional. Blank disables that provider. |
| `AGENTIRA_ENV` | backend | Leave unset. Defaults to `prod`, which disables the dev auth bypass. |

### Persistence

Two things must survive a redeploy:

- **Postgres** — a real volume, or a managed Postgres.
- **`/app/data` on the backend** — attachments live there. No volume means uploaded
  briefs and designs vanish on the next deploy.

### TLS

Put a reverse proxy in front of the frontend service (Caddy, nginx, your provider's
edge). The backend does not terminate TLS. If your provider gives private hostnames
that are IPv6-only, point `API_UPSTREAM` at the public edge instead — nginx's default
startup resolver is IPv4-only.

### Upgrading

```bash
git pull
docker compose build
docker compose up -d
```

Migrations are idempotent and run at startup (`scripts/bootstrap_db.py` → `init_db()`).
Back up Postgres before a major bump anyway.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `mcp` container exits (1) with `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` | You are on a build predating the `mcp<2` pin. mcp 2.x removed that module. Pull, rebuild. |
| `agentira daemon login` says "didn't return a usable verification URL (got '/cli-auth')" | `FRONTEND_URL` is not set on the backend. |
| Daemon logs `Runtime registration failed: HTTP Error 401` | The dev bypass names a profile that does not exist. `AGENTIRA_DEV_PROFILE` must name a real profile — `admin` is always seeded. |
| Runtimes appear in the API but stay `offline` forever, and nothing dispatches | The WebSocket is rejecting the daemon: `daemon ws: rejected unauthenticated/non-admin connect` in the backend logs. Re-run `agentira daemon login`, or set `AGENTIRA_DAEMON_API_KEY` with `AGENTIRA_ENV=dev` on a local stack. |
| Frontend 502 on `/api/*` | `API_UPSTREAM` / `API_HOST` do not match the backend's real address. |
| Backend exits: "JWT_SECRET required" | Set it. |
| Logs: "AGENTIRA_ADMIN_PASSWORD is unset in production" | Set it and redeploy — no admin was created, and signup is invite-only. |
| Signed in, but no admin powers | Invites with `--role member` grant `member`. Sign in as `admin` and promote. |
| Agents missing after first boot | Bootstrap didn't finish — check the logs for "agent templates seeded". |
| Attachments vanish after redeploy | No volume on `/app/data`. |
| MCP unreachable from an agent | Correct if you left MCP's public networking off — agents reach it through the backend, not directly. |

Logs:

```bash
docker compose logs -f backend
docker compose logs -f mcp
agentira daemon logs
```

## What this guide does not cover

- Horizontal scaling or multi-node deploys. One backend, one MCP, one Postgres.
- Object storage for attachments (S3 and friends) — on the roadmap.
- Sandbox enforcement. Sandbox modes are configured and logged today; per-adapter
  enforcement is Phase 2. **A runtime can currently touch what your user account can
  touch.** Run agents against repos you are willing to let them edit.
