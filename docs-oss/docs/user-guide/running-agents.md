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

## Concurrency

The daemon caps how many runs execute at once. Dispatches beyond the cap queue until a slot frees.

If an agent appears stuck at capacity, check for stale runs holding slots — see [Troubleshooting](./troubleshooting.md).
