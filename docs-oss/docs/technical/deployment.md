---
id: deployment
title: Deployment
sidebar_label: Deployment
---

# Deployment

Agentira runs anywhere that provides Docker and Postgres. This page uses Railway as the worked example; the same steps apply elsewhere.

## Deploy to Railway

### 1. Create the project

Provision a Railway project and add the Postgres plugin.

### 2. Deploy three services

All three build from the same repository with different Dockerfiles:

| Service | Dockerfile |
|---|---|
| Backend | `Dockerfile` |
| MCP | `Dockerfile.mcp` |
| Frontend | `frontend/Dockerfile` |

### 3. Wire the variables

The backend needs the database address and a JWT secret.

The MCP service needs **the same** database address and **the same** JWT secret. Use Railway variable references so they cannot drift:

```
DATABASE_URL = ${{Postgres.DATABASE_URL}}
JWT_SECRET   = ${{backend.JWT_SECRET}}
```

Backend and MCP are two entry points into one application. Divergent secrets produce authentication failures that are tedious to diagnose.

### 4. Mount a volume

Attach a volume to the backend at its data path, so attachments survive redeploys. One gigabyte is a reasonable starting point.

### 5. Point the frontend at the backend

Set `API_UPSTREAM` and `API_HOST` on the frontend service to your backend's address. They default to the Compose service name, which does not exist in a hosted deployment. `frontend/nginx.conf` substitutes them at container start.

### 6. Set `FRONTEND_URL`

Set `FRONTEND_URL` on the backend to your public frontend address.

Skipping this is the most common deployment mistake. Every `agentira daemon login` fails with "didn't return a usable verification URL" until it is set.

### 7. First sign-in

Migrations run automatically at startup. Sign in as the bootstrap administrator and change the password immediately.

Then mint invites for everyone else:

```bash
railway run --service backend \
  python scripts/create_invite.py --role admin
```

## Deploy with Docker Compose

Compose files for QA and production ship with the repository.

```bash
cp .env.prod.example .env.prod
# set JWT_SECRET and POSTGRES_PASSWORD

docker compose -p agentira-prod \
  -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file .env.prod up -d
```

The Compose files refuse to start when required values are missing. This is intentional.

Development, QA, and production use distinct ports and Compose project names, so all three can run on one host simultaneously.

## Deployment checklist

- [ ] `JWT_SECRET` set to a generated value, identical on backend and MCP
- [ ] `POSTGRES_PASSWORD` set
- [ ] `FRONTEND_URL` set to the public frontend address
- [ ] Persistent volume mounted for attachments
- [ ] `CORS_ALLOW_ORIGINS` restricted to your origins
- [ ] Bootstrap administrator password changed
- [ ] TLS terminated in front of the backend and frontend
- [ ] Database backups scheduled
- [ ] Frontend `API_UPSTREAM` and `API_HOST` pointing at the backend

## After deploying

Verify the full path rather than only that the site loads:

1. Sign in.
2. Mint an invite and redeem it.
3. Install the daemon on a workstation and run `agentira daemon login` against the public address.
4. Confirm `agentira runtime list` shows at least one runtime.
5. Create a project and run the kickoff task end to end.

Step 3 is the one that catches missing `FRONTEND_URL`. Step 5 catches dispatch and database problems.

## Post-deploy configuration

Some settings live in the interface, not in environment variables:

| Setting | Where |
|---|---|
| Conductor model and cadence | Conductor agent settings |
| Autonomous mode | Conductor agent settings |
| Gates | Project settings |
| Project members, including agents | Project settings |
| Webhooks | Project settings |
