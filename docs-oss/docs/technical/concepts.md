---
id: concepts
title: Conversations, turns, and runs
sidebar_label: Core concepts
---

# Conversations, turns, and runs

Three concepts carry every dispatch. Getting them straight explains most of Agentira's behaviour.

| Concept | What it is | Lifetime |
|---|---|---|
| **Conversation** | An agent's working memory for one scope | Per agent and scope. Long-lived. |
| **Turn** | One dispatch: a message and the agent's reply, sharing a trace identifier | Per dispatch |
| **Run** | An emergent span grouping the turns of one work episode | Per work episode. May span many turns. |

## Conversation

A conversation is keyed by agent and **scope**:

| Scope | Grain |
|---|---|
| `task:<task_id>` | One task |
| `chat:project:<project_id>` | Project-level discussion |
| `chat:default` | Workspace-level discussion |

The conversation is what a runtime's session resume keys off. Because the working directory for an agent and task is stable, the runtime can resume its own session rather than replaying history.

Scopes are isolated. Clearing one does not affect another, and context does not leak between projects. The Conductor's planning turns each get their own scope, which also means a planning turn starts with an empty history by construction.

## Turn

A turn is the atomic unit. It is always durable and always stoppable.

Every dispatch creates a turn, whether or not it produces work. A turn carries one trace identifier across the backend, the daemon, and the runtime, which is how events are correlated.

## Run

A run is not created for every turn. It **crystallises** when a turn produces work.

A turn becomes a run when any of these occur:

1. The worktree changes, according to the project's work-signal mode.
2. The agent registers an artifact.
3. The agent declares an outcome.

If none occur, the exchange stays a chat turn. This keeps the run list meaningful.

### Work-signal modes

| Mode | Counts as work |
|---|---|
| `working_tree` | Any change, including new untracked files. Default. |
| `tracked` | Only edits to files Git already knows |
| `committed` | Only a new commit |

The default is deliberately generous: an agent that creates a file without staging it still gets credit.

### Shadow registration

A run row is reserved at dispatch, before work happens, so logs and artifacts have a destination. If the turn produces nothing, the reserved row is deleted at completion.

This avoids the alternative, where an agent produces output with nowhere to put it.

## Why this shape

The model comes from failure modes in multi-day asynchronous work.

A single "session" concept cannot serve all three needs at once. Memory must persist across many work episodes. Cancellation must act on something atomic. Accounting, verdicts, and artifacts must attach to a work episode, which may take several dispatches.

Collapsing them produces familiar problems: chat that pollutes the work record, cancellation that either kills too much or too little, and cost accounting that cannot be attributed.

## Pause and resume

A comment on a running task pauses the run, captures the session, and resumes with the comment as the next turn — same run, same identifier.

This is possible because the turn is the atomic unit and the run is a span over turns. Adding a turn to an existing run needs no new run.

All of it survives a restart. In-flight state is recorded on disk, and the daemon's startup reaper kills zombie processes from prior runs.
