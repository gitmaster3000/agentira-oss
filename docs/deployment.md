# Deployment — Railway

This is the operator's guide. If you're a user signing up to use Agentira, see [getting-started.md](getting-started.md) instead.

Agentira is a four-service stack:

1. **backend** — FastAPI + SQLAlchemy, the REST API
2. **mcp** — the MCP server agents talk to
3. **frontend** — nginx serving the built React bundle, proxies `/api/*` to backend
4. **postgres** — managed by Railway

All four live in one Railway *project*. Backend + MCP + Postgres talk over Railway's internal network; only the frontend is publicly exposed.

## One-time setup (10 minutes)

### 1. Fork or push the repo

You need one GitHub repo on the deploying account: `<you>/agentira`. It is a monorepo —
backend, MCP and frontend all deploy from it, each with its own Dockerfile.

If you forked from this repo, you're done. Otherwise push your local clone.

### 2. Create the Railway project

1. railway.app → New Project → Empty Project. Name it `agentira` or `flowty`.
2. Add Postgres: + New → Database → Add PostgreSQL. Railway provisions it; copy the internal `DATABASE_URL` for later (you won't need it directly — backend reads it from the env Railway injects).

### 3. Deploy the backend service

1. + New → GitHub Repo → pick `<you>/agentira`. Service name: `backend`.
2. Settings → Build → Dockerfile Path: `Dockerfile` (this is the default).
3. Settings → Networking → Public Networking: leave **OFF**. Backend is internal-only.
4. Settings → Variables — paste:
   ```
   JWT_SECRET=<run: openssl rand -hex 32>
   AGENTIRA_ADMIN_PASSWORD=<run: openssl rand -base64 18>
   AGENTIRA_DB_URL=${{Postgres.DATABASE_URL}}
   RAILWAY_ENVIRONMENT=production
   PORT=8080
   ```
   The `${{Postgres.DATABASE_URL}}` syntax is Railway's variable reference — it auto-wires the Postgres add-on.

   **`AGENTIRA_ADMIN_PASSWORD` is required** (AP-194). In production the backend
   will not seed a default admin without it — and since signup is invite-only,
   an instance with no admin has no way in at all. On first boot the backend
   creates user `admin` with this password; store it in a password manager and
   rotate from the UI later.

   **`FRONTEND_URL=https://<your-frontend-domain>` is required** if you want
   `agentira daemon login` to work. The backend builds the browser approval link
   from it; unset, the CLI gets a relative path and refuses to continue.

   Optional — `CORS_ALLOW_ORIGINS=https://<your-frontend-domain>`. The frontend
   reaches the API same-origin through the nginx proxy, so the app works without
   it. Set it only if something calls the backend cross-origin directly; in
   production, left unset, cross-origin requests are blocked by design.
5. (Optional, for sign-in via Google/GitHub):
   ```
   GOOGLE_CLIENT_ID=<from console.cloud.google.com>
   GITHUB_CLIENT_ID=<from github.com/settings/developers>
   GITHUB_CLIENT_SECRET=<same place>
   ```
   Leave blank to only allow username+password signup.
6. Deploy. Watch the logs — you should see "Bootstrapping AgentIRA Database" then "Uvicorn running on http://0.0.0.0:8080".

### 4. Deploy the MCP service

1. + New → GitHub Repo → pick `<you>/agentira` again. Service name: `mcp`.
2. Settings → Build → Dockerfile Path: `Dockerfile.mcp`.
3. Settings → Networking → Public Networking: **OFF**.
4. Settings → Variables:
   ```
   JWT_SECRET=${{backend.JWT_SECRET}}
   AGENTIRA_DB_URL=${{Postgres.DATABASE_URL}}
   RAILWAY_ENVIRONMENT=production
   MCP_HOST=0.0.0.0
   MCP_PORT=8000
   ```
   The `${{backend.JWT_SECRET}}` reference reuses the secret you set on backend — they must match.
5. Deploy.

The MCP service currently uses the v1 Python SDK API. Keep the `mcp[cli]`
dependency below v2 until `backend/mcp_server.py` is migrated; the MCP image
build includes an import smoke check so an incompatible SDK fails during the
build instead of crashing the live service at startup.

### 5. Deploy the frontend service

1. + New → GitHub Repo → pick `<you>/agentira` again. Service name: `frontend`.
2. Settings → Build → Dockerfile Path: `frontend/Dockerfile`.
3. Settings → Networking → Public Networking: **ON**. Generate a domain (Railway gives you `<service>.up.railway.app`) or attach your own.
4. Settings → Variables:
   ```
   PORT=8080
   API_UPSTREAM=http://backend.railway.internal:8080
   API_HOST=backend.railway.internal
   ```
   `frontend/nginx.conf` substitutes both at container startup — no file edit, no rebuild. Change `backend` to whatever you actually named the backend service.

   Railway's private hostnames are IPv6-only and nginx's startup resolver is IPv4-only. If the proxy can't resolve the internal name, point `API_UPSTREAM` at the backend's public edge URL instead and set `API_HOST` to that hostname.
5. Go back to the **backend** service and set `FRONTEND_URL` to the domain you just generated. Redeploy it.

### 6. (Optional) Custom domain

Settings → Networking → Custom Domain on the frontend service. Railway shows you which CNAME records to add at your DNS provider.

### 7. Sign in

Visit your frontend domain → log in as **`admin`** with the `AGENTIRA_ADMIN_PASSWORD` you set. That account holds the admin role.

**There is no public sign-up.** Teammates join by invite only — mint one with `python scripts/create_invite.py --role member --org <org_id>` (or `--role admin` to hand someone their own org), then send them the link. Seven agents (Conductor, Planner, Backend Implementer, Frontend Implementer, Reviewer, DevOps, Agentira Guide) are already seeded.

## Attachments persistence (important)

Backend writes attachments to `data/attachments/` inside the container. Railway container disks are **ephemeral** — they reset on redeploy. For real use, attach a Volume:

1. Backend service → Settings → Storage → + New Volume.
2. Mount path: `/app/data`.
3. Size: 1GB is plenty for v1.
4. Redeploy.

Without a Volume, attachments survive only until the next deploy. Fine for testing; not for actual users.

## Updating the deployment

`git push` to your repo's `main` branch. Railway auto-builds + redeploys the affected service.

Migrations run automatically at startup (`scripts/bootstrap_db.py` → `services.bootstrap()` → `init_db()` → `run_migrations()`). They're idempotent on Postgres.

## Daemon CLI distribution (customers)

The backend Docker image bakes in the current `agentira-cli` wheel
(`Dockerfile` → `write_cli_manifest.py`). Public endpoints (no auth):

| Endpoint | Purpose |
|---|---|
| `GET /api/public/cli-release` | JSON: version + `install_url` |
| `GET /api/public/cli/wheels/{file}.whl` | Pip-installable wheel |
| `GET /api/public/install.sh` | Mac/Linux installer script |
| `GET /api/public/install.ps1` | Windows installer script |

Customers install with:

```bash
curl -fsSL https://YOUR-FRONTEND-DOMAIN/api/public/install.sh | bash
```

They upgrade with `agentira daemon update` after you redeploy backend with a
newer CLI (bump `agentira-cli/pyproject.toml` version before deploy).

Optional backend env var if Railway's proxy headers are wrong:

```
AGENTIRA_PUBLIC_URL=https://your-frontend-domain.up.railway.app
```

Use your **frontend** domain (the public URL), not the internal backend name.

## Logs + diagnostics

- Backend logs: Railway service → Logs tab.
- Backend metrics (request count, response time): Railway service → Metrics.
- Failed migration: backend won't start; the logs show the SQLAlchemy error.

## Costs

Railway pricing as of 2026: Hobby plan ~$5/mo includes credits enough for a small (4-service) stack at low traffic. Postgres backups cost extra. For real production traffic, move to Team plan + autoscale.

## What's NOT in this guide

- The daemon. The daemon runs on your (or your user's) **own machine** — it's the bridge between the cloud backend and the locally-installed `claude` CLI. Each user installs their own. See the daemon section of [getting-started.md](getting-started.md).
- Custom MCP servers. Bring your own MCP servers via the MCP registry (Agent Settings → MCP) once the workspace is up.

## Troubleshooting

| Symptom | Most likely cause |
|---|---|
| Frontend 502 on `/api/*` | nginx.conf `proxy_pass` doesn't match backend's service name |
| Backend exits with "JWT_SECRET required" | Missing env var — set it |
| Can log in but no admin powers / can't see admin pages | Signup grants `member`, not admin. Log in as `admin` (AGENTIRA_ADMIN_PASSWORD) and promote your user |
| Logs say "AGENTIRA_ADMIN_PASSWORD is unset in production" | Set it and redeploy — no admin was created |
| Backend exits with "could not connect to server" | `AGENTIRA_DB_URL` not wired to Postgres add-on |
| Sign-in works but agents missing | Backend hasn't bootstrapped — check logs for "agent templates seeded" |
| Attachments disappear after redeploy | No Volume mounted on `/app/data` |
| `daemon update` / installer says no CLI release | Backend not redeployed since CLI bump, or frontend not proxying `/api/public/*` |
| MCP unreachable from agents | MCP service public-networking is off (correct); agents reach it via the backend, not directly |
