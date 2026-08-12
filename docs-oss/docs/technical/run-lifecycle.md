---
id: run-lifecycle
title: Run lifecycle
sidebar_label: Run lifecycle
---

# Run lifecycle

## Dispatch

1. **Validate.** The backend confirms the task has an assignee, that the assignee is a project member, and that the caller may dispatch.
2. **Resolve sandbox mode.** The project mode overrides the agent default, then downshifts to what the runtime supports. The resolved mode is logged.
3. **Reserve a run.** A run row is created before work starts, so logs and artifacts have a destination.
4. **Record in-flight state.** Written to memory and disk, so a restart does not lose the turn.
5. **Enqueue in the outbox.** The frame is persisted before sending, and redelivered if unacknowledged.
6. **Send the dispatch frame** to the daemon over WebSocket.

## Execution

The daemon:

1. Accepts the frame and acknowledges it.
2. Checks the concurrency cap, queueing if needed.
3. Provisions the Git worktree for the declared repositories.
4. Builds the environment, including the agent's API key.
5. Starts the runtime as a subprocess.
6. Streams events back as they arrive.

The working directory is stable per agent and task; the worktree inside is recreated per run.

## Completion

A run ends in one of three ways.

**The agent declares an outcome** by calling `finish_run` with `succeeded`, `failed`, `blocked`, or `needs_input`.

**The process exits without declaring.** The daemon reports the exit. A clean exit with no declared outcome is a known false-green source — the run can appear successful while nothing was produced. Check the diff and artifacts.

**Something interrupts.** A pause captures the session for resume. A crash triggers automatic retry. A vanished daemon is caught by the reconciler.

On completion the backend evaluates the work signal. If the turn produced no work, the reserved run row is deleted.

## Crystallisation

A turn becomes a run when any of these occur:

- The worktree changed, per the project's work-signal mode
- An artifact was registered
- An outcome was declared

Otherwise the exchange remains a chat turn.

## Pause and resume

Pause sends a clean termination signal, captures the session handle, and marks the run paused. The next message resumes the same run with the message as its next turn.

A comment on a running task performs this automatically.

## Failure handling

| Failure | Response |
|---|---|
| Runtime subprocess crash | Automatic retry, resuming the session |
| Backend restart | In-flight turns recovered from disk |
| Daemon restart | Orphan reaper kills zombies; in-flight state reloaded |
| Daemon disappears | Reconciler sweep marks affected runs |
| Unacknowledged dispatch | Outbox redelivers within its time-to-live |
| Session cannot resume | One retry without resume, replaying stored history |

## Accounting

Token consumption and estimated cost are recorded per turn and aggregated to the run.

## Diagnosis

| Source | Contents |
|---|---|
| Run events (`get_run_events`) | Structured event stream |
| Run diagnostics (`get_run_diagnostics`) | Detail for failure analysis |
| `~/.agentira/runs/<id>/stdout.log` | Raw runtime output |
| `~/.agentira/runs/<id>/stderr.log` | Raw runtime errors |
| `~/.agentira/runs/<id>/meta.json` | Run metadata |
| `agentira daemon logs` | Daemon-side view |

When a run reports success but left nothing behind, read `stdout.log`. The agent often did honest work the runtime could not report — most commonly because the runtime lacks MCP support.
