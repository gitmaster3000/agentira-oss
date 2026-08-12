---
id: self-hosting
title: Self-hosting
sidebar_label: Self-hosting
---

# Self-hosting

Agentira is designed to be self-hosted. Nothing in a self-hosted deployment depends on a service the maintainers control.

For a local development stack, see [Install Agentira](../user-guide/install.md). This page covers running Agentira for real.

## What you need

| Component | Requirement |
|---|---|
| Container host | Anything that runs Docker |
| Database | Postgres 16 |
| Persistent volume | For attachments |
| Public address | Reachable by browsers and by daemons |
| TLS | A reverse proxy terminating HTTPS |

The daemon runs on each user's own machine, not on your server. You host the backend, the MCP server, the frontend, and the database.

## Services

| Service | Image source | Purpose |
|---|---|---|
| Backend | `Dockerfile` | REST API, gate engine, dispatch |
| MCP | `Dockerfile.mcp` | Tool server for agents |
| Frontend | `frontend/Dockerfile` | Static bundle behind nginx |
| Postgres | Official image or managed service | Database |

Backend and MCP share the database and the JWT secret. The MCP server is a second entry point into the same application, not a separate system.

## Before you expose it

**Change the bootstrap administrator password.** A fresh database creates `admin` with a known default.

**Set a real `JWT_SECRET`.** Generate with `openssl rand -hex 32`. Do not reuse the development value.

**Set `FRONTEND_URL`** to your public frontend address. Without it, `agentira daemon login` cannot build the browser approval link and every daemon login fails.

**Mount a persistent volume** at the attachments path. Without one, attachments are lost on redeploy.

**Restrict `CORS_ALLOW_ORIGINS`** to the origins you serve.

**Terminate TLS.** Daemon connections carry tokens and dispatch payloads.

See [Configuration](./configuration.md) for the full variable list.

## Registration model

There is no open registration form. The first administrator exists from bootstrap; everyone else joins by invite.

Mint invites from inside the backend container:

```bash
docker compose exec -e FRONTEND_URL=https://your-instance.example backend \
  python scripts/create_invite.py --role admin
```

Use `--role member --org <org_id>` to add someone to an existing organisation.

This means an exposed instance is not open to the internet by default. It is still worth putting it behind whatever access control your situation calls for.

## Database

Postgres 16. Migrations run automatically at startup and are idempotent, so deploys need no manual migration step.

Back up the database on your provider's normal schedule. It holds every board, run, conversation, and audit record.

Give the database room. Conversation history grows, and query spill on a full volume produces failures that look unrelated to disk.

## Upgrades

1. Back up the database.
2. Pull the new images.
3. Restart. Migrations apply at startup.

Agent prompts and other user-edited fields are seeded only when empty, so an upgrade does not overwrite your edits.

## Users and daemons

Each person who wants agents doing work installs the daemon on their own machine and authorises it against your instance:

```bash
pip install -e agentira-cli/
agentira daemon login --api-url https://your-instance.example
agentira daemon start
```

They also need at least one coding runtime installed locally.

Your server never executes agent work, and never needs access to user repositories.

## Monitoring

| Signal | Why |
|---|---|
| Backend health endpoint | Liveness |
| Database volume usage | A full volume produces confusing failures |
| Failed runs | Rising counts indicate a runtime or credential problem |
| Daemon connections | Zero connections means no work can execute |
| Planning turn errors | Relevant when the Conductor is autonomous |

## Limitations to plan around

**Attachments are stored on a local volume.** Object storage is on the roadmap. Size the volume and back it up.

**Sandbox enforcement is incomplete.** Modes are configured and logged but not enforced per runtime. See [Sandbox](./sandbox.md).

**Daemon installation is manual.** Signed installers are on the roadmap.

**Evidence providers need GitHub credentials.** Without them, `github_pr`, `ci`, and `commit` answer `unknown` and block transitions.
