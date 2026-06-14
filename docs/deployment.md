# Deployment — Railway

This is the operator's guide. If you're a user signing up to use Agentira, see [getting-started.md](getting-started.md) instead.

Agentira is a four-service stack:

1. **backend** — FastAPI + SQLAlchemy, the REST API
2. **mcp** — the MCP server agents talk to
3. **frontend** — nginx serving the built React bundle, proxies `/api/*` to backend
4. **postgres** — managed by Railway

All four live in one Railway *project*. Backend + MCP + Postgres talk over Railway's internal network; only the frontend is publicly exposed.

## One-time setup (10 minutes)

### 1. Fork or push the repos

You need two GitHub repos on the deploying account:
- `<you>/agentira` — backend + MCP
- `<you>/agentira-frontend` — frontend

If you forked from this repo, you're done. Otherwise push your local clones.

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
   will not seed a default admin without it — public signup only grants the
   `member` role, so without this var the workspace would have no administrator.
   On first boot the backend creates user `admin` with this password; store it
   in a password manager and rotate from the UI later.

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

### 5. Deploy the frontend service

1. + New → GitHub Repo → pick `<you>/agentira-frontend`. Service name: `frontend`.
2. Settings → Build → Dockerfile Path: `Dockerfile`.
3. Settings → Networking → Public Networking: **ON**. Generate a domain (Railway gives you `<service>.up.railway.app`) or attach your own.
4. Settings → Variables:
   ```
   PORT=8080
   ```
5. Open `nginx.conf` in your frontend repo — the `proxy_pass` line says `http://flowty-api.railway.internal:8080`. **You must change `flowty-api` to match your backend service's name.** If you named the backend service `backend`, change it to `http://backend.railway.internal:8080`. Push the change. Railway redeploys.

### 6. (Optional) Custom domain

Settings → Networking → Custom Domain on the frontend service. Railway shows you which CNAME records to add at your DNS provider.

### 7. Sign in

Visit your frontend domain → log in as **`admin`** with the `AGENTIRA_ADMIN_PASSWORD` you set. That account holds the admin role. (Public **Sign Up** creates `member`-role users, not admins — use it for teammates, then promote them from the UI.) The Conductor and the five default agents (Planner, Backend Implementer, Frontend Implementer, Reviewer, DevOps) are already seeded.

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
| MCP unreachable from agents | MCP service public-networking is off (correct); agents reach it via the backend, not directly |
