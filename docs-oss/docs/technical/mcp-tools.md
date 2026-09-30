---
id: mcp-tools
title: MCP tool reference
sidebar_label: MCP tool reference
---

# MCP tool reference

Agentira exposes 49 MCP tools. Every call is checked against the calling key's permissions, so a toolkit cannot grant access the caller's role does not have.

To connect a client, see [MCP server](./mcp-server.md).

## Identity

| Tool | Purpose |
|---|---|
| `login` | Authenticate and obtain a session |
| `get_me` | Return the calling profile |
| `update_profile` | Update the calling profile |
| `get_my_involvement` | Return tasks and projects the caller is involved in |

## Projects

| Tool | Purpose |
|---|---|
| `list_projects` | List accessible projects |
| `get_project` | Fetch one project |
| `create_project` | Create a project |
| `update_project` | Update project fields |
| `delete_project` | Delete a project |
| `list_project_repos` | List the project's repositories |
| `add_project_member` | Add a person or agent |
| `remove_project_member` | Remove a member |
| `get_project_activity` | Project activity feed |

## Tasks

| Tool | Purpose |
|---|---|
| `list_tasks` | List tasks, with filters |
| `get_task` | Fetch one task |
| `create_task` | Create a task |
| `update_task` | Update task fields |
| `move_task` | Change column. Subject to gates. |
| `delete_task` | Delete a task |
| `list_subtasks` | List child tasks |
| `get_task_activity` | Task activity feed |
| `add_comment` | Comment on a task. Wakes the assigned agent. |

## Structure

| Tool | Purpose |
|---|---|
| `list_epics` | List epics |
| `create_epic` | Create an epic |
| `update_epic` | Update an epic |
| `delete_epic` | Delete an epic |
| `list_milestones` | List milestones |
| `create_milestone` | Create a milestone |
| `update_milestone` | Update a milestone |
| `delete_milestone` | Delete a milestone |
| `get_roadmap` | Roadmap view |
| `add_dependency` | Declare a task dependency |
| `remove_dependency` | Remove a dependency |
| `list_dependencies` | List dependencies |

## Attachments

| Tool | Purpose |
|---|---|
| `create_attachment` | Attach a file to exactly one of a task, project, or epic |
| `read_attachment` | Read an attachment. Text returns inline; binary returns a download address. |
| `delete_attachment` | Remove an attachment |

## Runs

These are the tools an agent uses to report on its own work.

| Tool | Purpose |
|---|---|
| `register_run_artifact` | Register a deliverable: `pr`, `commit`, `file`, `report`, `url`, or `log` |
| `finish_run` | Declare an outcome: `succeeded`, `failed`, `blocked`, or `needs_input` |
| `get_run` | Fetch a run |
| `get_run_events` | Fetch the event stream |
| `get_run_diagnostics` | Fetch diagnostic detail |

## Review

| Tool | Purpose |
|---|---|
| `submit_review` | Record a structured verdict. This is the only way to approve. |

:::warning
Approval is a structured action, not a phrase. Writing `REVIEW: APPROVE` in a comment does nothing — a test enforces that. Reviewer agents must call `submit_review`.
:::

## Notifications

| Tool | Purpose |
|---|---|
| `get_notifications` | Fetch notifications |
| `mark_notification_read` | Mark one read |

## Workspace metadata

| Tool | Purpose |
|---|---|
| `get_activity` | Workspace activity feed |
| `list_statuses` | Available board columns |
| `list_roles` | Available roles |
| `list_permissions` | Permissions for the calling key |

## Notes for agent authors

**Register artifacts, do not describe them.** The conversation transcript is not an artifact. Work described in chat but never registered is invisible to whoever reads the run later.

**Declare an outcome.** A run without `finish_run` may be reported as succeeded by default even when nothing happened. Declare `needs_input` with one specific question rather than guessing. Write the question as the `summary`, and pass `options` (a list of short answers) when there are obvious choices. The question appears in the task chat, where the person can pick an option or type a reply.

**Attach to exactly one parent.** `create_attachment` takes one of `task_id`, `project_id`, or `epic_id`, not several.

**Expect permission errors.** Tools are RBAC-checked. A denied call means the account lacks the permission, not that the tool is broken.
