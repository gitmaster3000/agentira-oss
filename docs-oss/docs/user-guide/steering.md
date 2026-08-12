---
id: steering
title: Steering a run
sidebar_label: Steering a run
---

# Steering a run

Commenting on a task is the primary way you direct an agent. It works whether the agent is running, paused, or finished.

## What a comment does

| Run state | Effect |
|---|---|
| Running | Pauses the run cleanly, captures the session, then resumes immediately with your comment as the next turn. Same run. |
| Paused, blocked, or awaiting input | Resumes the run with your message |
| Finished | Starts a fresh turn. If that turn produces work, a new run is created. |

When a run pauses to take your comment, the agent keeps full context, including the fact that you interrupted it.

## When to steer

Comment when you see an agent:

- Working on the wrong thing
- Making an assumption you know is wrong
- Asking a question with the `needs_input` outcome
- Heading toward a design you do not want

You do not need to stop the run first. Commenting handles that.

Examples that work well:

> Use pytest, not unittest.

> The auth token is in the `Authorization` header, not a cookie. Check `backend/jwt_auth.py`.

> Stop adding features. Get the failing test passing, then stop.

## Clearing an agent's memory

An agent keeps a conversation per scope. When an agent has gone down a path you cannot talk it out of, clear that memory.

Type `/clear` in the chat thread and send it.

This clears, for the current scope only:

- The agent's conversation memory
- The runtime session handle
- The stored messages

It does **not** touch runs, diffs, artifacts, comments, or any other scope. Prior work is safe.

Use `/clear` when correcting the agent costs more than restarting it.

## Scopes

A conversation belongs to a scope, which sets what the agent remembers:

| Scope | Memory covers |
|---|---|
| `task:<id>` | One task |
| `chat:project:<id>` | Project-level discussion |
| `chat:default` | Workspace-level discussion |

Scopes are isolated. Clearing one leaves the others intact, and work in one does not leak into another.

## Stop and resume

**Stop** pauses. It sends a clean termination signal, captures the session, and marks the run paused. Your next message resumes it.

**Resume** continues a paused run from exactly where it stopped.

Both survive a restart of the daemon or the backend. In-flight state is recorded on disk.
