---
id: notifications
title: Notifications and webhooks
sidebar_label: Notifications
---

# Notifications and webhooks

## In-app notifications

The bell icon shows an inbox of events relevant to you: assignments, comments on your tasks, run outcomes, and mentions.

Run notifications show who is working on what: the agent's name, what happened (started working, finished, failed), the task key and title, and pills for status, project, and — once a run ends — duration, cost, and pull request. A failed run shows its reason inline. The bell shows a compact one-line version; the Inbox page shows the full card.

Mark items read individually or clear the inbox.

Delivery is a hybrid of push and polling. Push gives sub-second delivery when the connection is healthy; polling catches anything a dropped connection missed. You do not configure this.

## Choosing what you get, and where

When someone on one of your projects creates a task, a bug or an epic, you can be told about it. Open **Settings → Notifications** and tick, for each of those three things, where you want to hear about it:

- **In the app** — shows up in your Inbox and the bell. On by default.
- **Email** — sent to your account email. Off by default; needs email set up on the server.
- **Phone / browser** — a push alert that arrives even when Agentira is closed. Off by default.

You are never notified about things you created yourself.

To get phone alerts, also press **Turn on** under *This device* in the same page, once per phone or browser, and allow notifications when asked. On iPhone, add Agentira to your Home Screen first. The server admin must set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT` (see Configuration).

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
