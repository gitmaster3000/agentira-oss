---
id: rest-api
title: REST API
sidebar_label: REST API
---

# REST API

The REST API serves the browser and the CLI. Agents normally use [MCP](./mcp-server.md) instead, but both surfaces share one services layer and one permission model.

## Base address

| Environment | Address |
|---|---|
| Development | `http://localhost:8111` |
| QA | `http://localhost:8112` |
| Hosted | Your deployment address |

Interactive API documentation is served at `/docs` by the FastAPI application.

## Authentication

Two mechanisms:

**JWT.** Obtained by signing in. Used by the browser. Stateless.

**API key.** Sent as `Authorization: Bearer <key>`. Used by the CLI, service accounts, and external tools.

## Route groups

| Prefix | Domain |
|---|---|
| `/api/projects` | Projects, members, settings |
| `/api/tasks` | Tasks, comments, transitions |
| `/api/epics` | Epics |
| `/api/attachments` | File attachments |
| `/api/profiles` | Accounts and profiles |
| `/api/notifications` | Notification inbox |
| `/api/home` | Home page data in one response, plus the per-user tile layout |
| `/api/invites` | Invite minting, cancelling (`DELETE /api/invites/{id}`) and redemption |
| `/api/service-accounts` | API-key identities |
| `/api/webhooks` | Outbound webhook configuration |
| `/api/forge/*` | Agents, runs, conversations, dispatch |

### Batch task creation

`POST /api/projects/{project_id}/tasks/batch` (MCP: `create_tasks`) creates a whole plan in one all-or-nothing call.

```json
{"tasks": [
  {"ref": "schema", "title": "Design schema"},
  {"ref": "api", "title": "Build API", "priority": "high", "depends_on_refs": ["schema"]}
]}
```

Each entry takes the same fields as `POST /api/tasks` (only `title` required) plus a unique `ref` you choose and optional `depends_on_refs` (refs of other entries in the same batch; forward references are fine). Response: `[{"ref", "id", "key"}]` in input order.

The call is atomic: a missing or duplicate `ref`, an unknown `depends_on_refs` entry, a self-dependency, a cycle, a bad field value, an empty batch or more than 200 entries returns `400` and nothing is created (no tasks, no dependencies, no task numbers used).

`/api/forge/*` covers agent orchestration. The prefix is historical and does not indicate a separate product.

## Daemon WebSocket

```
/api/forge/daemon/ws
```

The daemon holds this connection to receive dispatch frames and stream events back. It authenticates with the daemon token from `agentira daemon login`, or with a development API key when `AGENTIRA_ENV=dev`.

Heartbeat intervals and timeouts are configurable. See [Configuration](./configuration.md).

## Gate rejections

A transition that fails its gates returns HTTP 422 with a structured body naming the failed gates:

```json
{
  "detail": {
    "failed_gates": [
      {
        "gate": "dod_complete",
        "reason": "3 of 7 definition-of-done items are unchecked"
      }
    ]
  }
}
```

Clients display the reasons rather than a generic error. See [Gates and evidence](./gates-and-evidence.md).

## Permissions

Every route is checked against the caller's profile. A denied call returns 403 with the missing permission named.

Roles are instance-wide; project membership is per project. Both are evaluated.

## Migrations

Migrations run automatically at startup through the bootstrap script, and are idempotent. No manual migration step is required on deploy.

## Attachment preview

The in-app preview (`AttachmentPreview.jsx`) reuses `GET /api/attachments/{id}/download`: the UI fetches the bytes with the bearer token and shows them from a `blob:` URL, so no new endpoint or auth path exists. Security: blob MIME type is forced from the file extension (never the server's `Content-Type`); only image/PDF/text extensions are previewable; SVG is shown via `<img>` (scripts do not run); Markdown is rendered by `react-markdown` without raw HTML; HTML files are never previewed. Access control is unchanged (`enforce_attachment_route_access`).


## Home page

`GET /api/home` returns everything the Home page renders in a single response, scoped to the projects you are a member of:

| Field | Contents |
|---|---|
| `week` | `done` (finished this week), `due` (open, due this week), `late` (open, past due), `planned` (all tasks) |
| `projects` | Per project: id, name, key, colour, description, `pct_done`, `open`, `due_this_week`, `late`, first 5 member avatars plus `member_count`, `last_updated`, `done_per_week` (last 6 weeks, oldest first) |
| `activity` | The last 20 task events across those projects: actor, action, task key and title, project, time |
| `people` | Each member across those projects: `open` tasks and `days_done_this_week` |
| `week_summary` | Latest week summary text, or `null` |

Weeks start on Monday (UTC). "Finished" uses `tasks.completed_at`, set when a task enters `done` and cleared when it leaves, so later edits to a done task do not count it again. Existing done tasks were backfilled from their latest move into `done` (falling back to `updated_at`). The endpoint issues a fixed number of queries regardless of project or task count (asserted in `backend/tests/test_home_api.py`); date filters are backed by indexes on `tasks.due_date`, `tasks.completed_at` and `activities.created_at`.

`GET /api/home/layout` and `PUT /api/home/layout` read and replace the caller's tile layout, stored on their profile. The body is `{"layout": [["tile_id", "size"], ...]}` (at most 50 tiles).
