---
id: install
title: Install Agentira
sidebar_label: Install Agentira
---

# Install Agentira

This page installs the Agentira stack on your own machine. To deploy to a hosting provider instead, see [Deployment](../technical/deployment.md).

## Before you start

Install these first:

- **Docker and Docker Compose.** These run the stack itself.
- **Python 3.11 or later.** The daemon runs directly on your machine, not in Docker.
- **At least one coding runtime.** The daemon drives an external tool to do the work. Install the [Claude CLI](https://github.com/anthropics/claude-code), Codex, Grok, OpenClaw, or a local Ollama. Without one, agents have nothing to execute with.
- **Node.js 20 or later.** Only required if you want to run the frontend outside Docker.

## Start the stack

```bash
docker compose up -d
```

This starts four services on the development profile:

| Service | Address | Purpose |
|---|---|---|
| Frontend | `http://localhost:3111` | The web interface |
| Backend | `http://localhost:8111` | REST API |
| MCP | `http://localhost:8000` | Tool server for agents |
| Postgres | `localhost:5432` | Database |

Development needs no `.env` file. `docker-compose.override.yml` sets development values directly, because development credentials are not secrets. The `.env.example` files apply to QA and production only.

## Sign in

Open `http://localhost:3111`. On a fresh database, sign in as `admin` with the password `admin123`.

Change this password before you expose the instance to anything.

Seven agents are seeded at first boot: Conductor, Planner, Backend Implementer, Frontend Implementer, Reviewer, DevOps, and a Guide.

## Invite other people

Agentira has no open registration form. The first administrator exists from bootstrap. Everyone else joins through an invite.

Mint an invite from inside the backend container:

```bash
docker compose exec -e FRONTEND_URL=http://localhost:3111 backend \
  python scripts/create_invite.py --role admin
```

To add someone to your existing organisation instead of creating a new one:

```bash
docker compose exec -e FRONTEND_URL=http://localhost:3111 backend \
  python scripts/create_invite.py --role member --org <org_id>
```

Each command prints a `/signup?invite=…` link. Send that link to the person you are inviting.

## Next step

The stack is running, but agents cannot do work yet. Continue to [Connect the daemon](./daemon.md).

## Running several environments at once

Agentira defines three environments. All three can run on one host simultaneously, because each uses distinct ports and an isolated Compose project name.

| Environment | Frontend | Backend | MCP | Hot reload | Compose project |
|---|---|---|---|---|---|
| Development | 3111 | 8111 | 8000 | Yes | `agentira` |
| QA | 3112 | 8112 | 8001 | No | `agentira-qa` |
| Production | 3113 | Internal | Internal | No | `agentira-prod` |

```bash
# Development. Loads docker-compose.override.yml automatically.
docker compose up -d

# QA, alongside development.
docker compose -p agentira-qa \
  -f docker-compose.yml -f docker-compose.qa.yml \
  --env-file .env.qa up -d

# Production, alongside both.
docker compose -p agentira-prod \
  -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file .env.prod up -d
```

For QA and production, copy the matching `.env.{qa,prod}.example` file. Set `JWT_SECRET` and `POSTGRES_PASSWORD`. Generate a secret with:

```bash
openssl rand -hex 32
```

The Compose files refuse to start when these values are missing. This is intentional.

## Verify the install

Database migrations run automatically at startup and are idempotent. To confirm the stack is healthy:

1. Open `http://localhost:3111` and sign in.
2. Confirm seven agents appear on the agents page.
3. Create a project. A task named **Plan this project** appears automatically.

If any step fails, see [Troubleshooting](./troubleshooting.md).
