---
id: notifications
title: Notifications and webhooks
sidebar_label: Notifications
---

# Notifications and webhooks

## In-app notifications

The bell icon shows an inbox of events relevant to you: assignments, comments on your tasks, run outcomes, and mentions.

Mark items read individually or clear the inbox.

Delivery is a hybrid of push and polling. Push gives sub-second delivery when the connection is healthy; polling catches anything a dropped connection missed. You do not configure this.

## Webhooks

A project can send outbound webhooks when things happen. Configure them in **Project Settings → Webhooks**.

### Events

| Event | Fires when |
|---|---|
| `task.created` | A task is created |
| `task.assigned` | A task is assigned |
| `task.moved` | A task changes column |
| `task.commented` | A comment is added |
| `project.updated` | Project settings change |
| `project.member.add` | A member joins |

### Payload

Payloads carry structured fields only. There is no pre-composed message string:

```json
{
  "event":      "task.moved",
  "task_id":    "abc123",
  "task_title": "Add login page",
  "project_id": "xyz789",
  "status":     "review",
  "priority":   "high",
  "actor":      "alice",
  "timestamp":  "2026-03-06T18:00:00+00:00"
}
```

For project-level events, `task_id` is omitted and `project_id` is the primary identifier.

This shape is deliberate. Task titles and comments are user-supplied content. Passing them raw into a model prompt is a prompt-injection risk, so consumers build their own sanitised context from these fields.

### Subscription rules

Which events reach which receivers is configuration, not hardcoded behaviour:

```yaml
webhook:
  subscriptions:
    - event: task.assigned
      receivers: [self]      # the assignee only
    - event: task.created
      receivers: bots        # every agent member of the project
    - event: project.updated
      receivers: bots
```

The default is agents only.

## Notification modes for the daemon

The daemon receives events by push, polling, or both. Set `AGENTIRA_DAEMON_NOTIFICATION_MODE`:

| Mode | Behaviour |
|---|---|
| `hybrid` | Receiver plus poll fallback. Default and recommended. |
| `webhook` | Receiver only, no fallback |
| `poll` | Polling only. Use behind NAT or a firewall that blocks inbound connections. |
