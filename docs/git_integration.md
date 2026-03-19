# Git Integration Guide

## Overview

Tasks in Agentira can be linked to git branches, PRs, and commits. Data flows in two ways:

1. **Manual** — set branch/PR URL directly on a task via UI, REST API, or MCP
2. **Automatic** — GitHub webhooks parse commit messages for task IDs and auto-link

## Task Fields

| Field | Type | Description |
|-------|------|-------------|
| `branch` | string | Git branch name or URL (click-to-edit in UI, copy checkout command) |
| `pr_url` | string | Pull request URL (clickable link in UI) |

Both fields are available on:
- **REST API**: `PATCH /api/tasks/{id}` with `branch` and/or `pr_url` in body
- **MCP**: `update_task(task_id, branch="...", pr_url="...")`
- **Frontend**: TaskDetailPanel, TaskDetailModal, TaskPage — inline click-to-edit fields

## Branch Suggestion

`GET /api/tasks/{task_id}/suggest-branch` returns a suggested branch name derived from the task ID and title:

```json
{
  "branch": "task/a8fcff2b4efb-fix-login-bug",
  "command": "git checkout -b task/a8fcff2b4efb-fix-login-bug"
}
```

Frontend API: `api.suggestBranch(taskId)`

## Webhook Auto-Sync

When a GitHub webhook delivers a push or PR event:

- **Commits**: If `task.branch` is empty, it is auto-set from the commit's branch
- **PRs**: `task.pr_url` is auto-set from the PR URL. If `task.branch` is empty, it is also set from the PR's head branch

### Task ID Patterns

Include a task ID in commit messages or PR titles/body:

- `[TASK-a8fcff2b4efb]`
- `task:a8fcff2b4efb`

### Webhook Endpoint

`POST /api/webhooks/github` — receives GitHub push and pull_request events.

## DOD Items via MCP

The `update_task` MCP tool now supports `dod_items`:

```
update_task(task_id, dod_items=[
  {"text": "Unit tests", "checked": true},
  {"text": "Code review", "checked": false}
])
```

## Linked Code (Read-Only)

Commits and PRs linked via webhook or manual `POST /api/tasks/{id}/commits` appear in a read-only list below the branch/PR fields in the UI. Each entry shows:

- Commit SHA (7-char) or PR number
- Message/title
- Author, branch
- PR state badge (open/closed/merged)
- External link to GitHub
