---
id: development-setup
title: Development setup
sidebar_label: Development setup
---

# Development setup

## Prerequisites

- Docker and Docker Compose, running
- Python 3.11 or later
- Node.js 20 or later
- At least one coding runtime, if you want to exercise agent dispatch

## Start the stack

```bash
docker compose up -d
```

Four services start on the development profile:

| Service | Address |
|---|---|
| Frontend | `http://localhost:3111` |
| Backend | `http://localhost:8111` |
| MCP | `http://localhost:8000` |
| Postgres | `localhost:5432` |

Development needs no `.env` file. `docker-compose.override.yml` sets development values directly, because development credentials are not secrets.

Sign in as `admin` / `admin123`.

Both the backend and the frontend hot-reload in this profile.

## Install the CLI

```bash
pip install -e agentira-cli/
```

For a local stack you can skip browser authorisation:

```bash
AGENTIRA_DAEMON_API_URL=http://127.0.0.1:8111 \
AGENTIRA_DAEMON_API_KEY=dev-daemon-key-local-only \
  agentira daemon start
```

The static key is gated on `AGENTIRA_ENV=dev` and does nothing elsewhere.

## Run the tests

Docker must be running. The suite starts an ephemeral Postgres container.

```bash
python -m pytest backend/tests/ -q
```

One file while iterating:

```bash
python -m pytest backend/tests/test_gates.py -q
```

CLI tests:

```bash
python -m pytest agentira-cli/tests/ -q
```

Frontend build:

```bash
cd frontend && npm ci && npx vite build
```

See [Testing](./testing.md) for the fixture rules. They are strict, and ignoring them is the most common reason a first pull request needs rework.

## Build the documentation

```bash
cd docs-oss
npm install
npm start          # local preview with hot reload
npm run build      # production build, fails on broken links
```

Run `npm run build` before submitting documentation changes. Broken links fail the build by design.

## Repository layout

```
agentira/
├── backend/            # FastAPI application
│   ├── forge/          # agent orchestration, self-contained
│   └── tests/          # backend test suite
├── agentira-cli/       # CLI and daemon
│   └── agentira_cli/runtimes/   # runtime adapters
├── frontend/           # React and Vite interface
├── templates/          # agent and workflow templates
├── scripts/            # bootstrap and operational scripts
├── docs-oss/           # this documentation site
└── docker-compose*.yml
```

## Common problems

**Tests fail immediately.** Docker is not running. The suite needs it for Postgres.

**The daemon finds no runtime.** Install one and confirm it is on your `PATH`, then restart the daemon.

**Port already in use.** Another environment may be running. Development, QA, and production use distinct ports and Compose project names, so check for a stray stack.

**Frontend cannot reach the backend.** Confirm all four services are healthy with `docker compose ps`.
