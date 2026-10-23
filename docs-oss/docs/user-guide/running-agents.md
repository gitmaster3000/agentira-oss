---
id: running-agents
title: Running agents
sidebar_label: Running agents
---

# Running agents

## Start a run

Open a task and select **Run**. The task must have an assignee, and that assignee must be a project member.

What happens next:

1. The backend reserves a run record, so logs and artifacts have somewhere to go before work starts.
2. The backend sends a dispatch frame to your daemon over WebSocket.
3. The daemon prepares a Git worktree for this agent and task.
4. The daemon starts the runtime as a subprocess.
5. Events stream back to the run page as they occur.

## Where the agent works

Each agent and task pair gets a stable working directory:

```
~/.agentira/agents/<agent>/home/repos/<project>/task-<task-id>/
```

The directory persists across every run and chat in that task, which is what allows a runtime to resume a prior session. The Git worktree inside it is recreated per run.

Run logs are written to:

```
~/.agentira/runs/<run-id>/
├── stdout.log
├── stderr.log
└── meta.json
```

## Run controls

| Control | Effect |
|---|---|
| **Run** | Dispatch the assigned agent |
| **Stop** | Pause the run. Sends a clean termination signal and captures the session so it can resume. |
| **Resume** | Continue a paused run from where it stopped |
| **Restart** | Start a fresh run for the same task and agent, with context from the previous outcome |

Stop is a pause, not a cancel. Agentira captures the session so your next message continues the work. To end a run outright, cancel it explicitly from the run page.

## What counts as a run

Every dispatch is a **turn**. A turn becomes a **run** only when it produces work. This keeps the run list meaningful — asking an agent a question does not create a run card.

A turn becomes a run when any of these occur:

- The worktree changes, according to the project's run-detection mode.
- The agent registers an artifact.
- The agent declares an outcome.

If none occur, the exchange stays a chat turn. You still see the conversation.

## Outcomes

An agent finishes by declaring one of:

| Outcome | Meaning |
|---|---|
| `succeeded` | The work is complete |
| `failed` | The agent tried and could not complete the work |
| `blocked` | Something outside the agent's control prevents progress |
| `needs_input` | The agent needs an answer from you |

Comment on the task to respond to `needs_input` or `blocked`. Your comment resumes the run.

## Reliability

Agentira expects processes to die and recovers rather than losing work:

- **Transient crashes retry.** If the runtime subprocess crashes mid-run, the session resumes automatically.
- **Restarts survive.** In-flight turns are recorded on disk, so a backend or daemon restart does not lose them.
- **Zombies are reaped.** On startup the daemon kills orphaned processes from earlier runs.
- **Vanished daemons are reconciled.** A periodic sweep marks runs whose daemon disappeared.

## Staying signed in

The daemon signs in with `agentira daemon login`. That sign-in is renewed automatically, so the daemon does not drop off after a week:

- **Renewed before it runs out.** When less than a day of sign-in is left, the daemon quietly gets a fresh one. Each device also holds a long-lived key that lasts 90 days and resets every time it is used, so a daemon that keeps running stays signed in indefinitely.
- **Renewed when the server says no.** If the server rejects a request as signed out, the daemon renews and retries once.
- **Visible when it cannot renew.** If the sign-in cannot be renewed (for example the device was removed, or the daemon was off for more than 90 days), the daemon writes this to its log, at most once every 10 minutes, and keeps retrying with growing pauses:

  ```
  Agentira daemon is signed out — run `agentira daemon login`
  ```

  Agents on that computer show as **offline** with a plain reason, such as "Agentira hasn't heard from Ali's Mac for 12 minutes. Its connector may be stopped or signed out."
- **Fixing it.** Run `agentira daemon login` again. A daemon that is still running picks up the new sign-in on its own; no restart needed.
- **Signing a device out.** `agentira daemon logout` removes the credentials and cancels the device's long-lived key on the server.

A daemon signed in with an older version keeps working as before until its week runs out; run `agentira daemon login` once more to get automatic renewal.

## Concurrency

The daemon caps how many runs execute at once. Dispatches beyond the cap queue until a slot frees.

If an agent appears stuck at capacity, check for stale runs holding slots — see [Troubleshooting](./troubleshooting.md).
