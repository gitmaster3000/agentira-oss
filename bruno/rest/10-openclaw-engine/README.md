# Bruno: OpenClaw engine agents (local docker)

Integration requests against a **running Agentira backend** (local docker).  
Data is seeded through **Agentira REST APIs** (project → task → agent → run).

## Prerequisites

```bash
# from repo root — start backend (adjust compose file as needed)
docker compose up -d backend   # or your local stack on :8000

# JWT / API key with admin rights
export AGENTIRA_API_KEY='…'
```

Set `apiKey` in Bruno env `local-docker` (or pass via CLI).

## Run with bruno-cli

```bash
# install once
npm i -g @usebruno/cli
# or: npx @usebruno/cli

cd bruno
bru run rest/10-openclaw-engine \
  --env local-docker \
  --env-var apiKey="$AGENTIRA_API_KEY" \
  --output results-openclaw.json
```

Open the folder in Bruno GUI to inspect request/response payloads.

## What is covered

| Step | API | Purpose |
|------|-----|---------|
| health | `GET /docs` | Backend up |
| project | `POST /api/projects` | Seed project |
| runtimes | `GET /api/forge/runtimes` | Find openclaw runtime id |
| task | `POST /api/tasks` | Seed task (frontend-shaped) |
| agent | `POST /api/forge/agents` | Seed agent on openclaw runtime |
| patch | `PATCH …/agents/{id}` | runtime_type=openclaw + system_prompt |
| get | `GET …/agents/{id}` | Detail shape |
| prepare-run | `POST …/tasks/{id}/prepare-run` | Run row for desk path |
| runs | `GET …/tasks/{id}/runs` | List runs |
| messages | `GET …/agents/{id}/messages?scope_key=task:…` | Chat scope contract |
| cleanup | `DELETE /api/projects/{id}` | Tear down |

Daemon-side unit tests cover `ar-<id>` session keys and workspace bind  
(`agentira-cli/tests/test_openclaw_engine.py`). Full live OpenClaw dispatch  
is intentionally not required for this suite so CI/local docker stays light.
