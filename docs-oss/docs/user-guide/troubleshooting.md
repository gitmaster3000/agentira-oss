---
id: troubleshooting
title: Troubleshooting
sidebar_label: Troubleshooting
---

# Troubleshooting

## The agent does not reply

Check the daemon is running and registered:

```bash
agentira daemon status
agentira daemon logs
```

The log must show a successful WebSocket registration. If it does not, restart the daemon.

Then confirm the agent is a member of the project. An agent that is not a member cannot be dispatched.

## No runtime is available

```bash
agentira runtime list
```

An empty list means the daemon found no supported tool on your `PATH`. Install one:

```bash
npm i -g @anthropic-ai/claude-code
```

Restart the daemon afterwards so it re-detects.

## `agentira daemon login` fails

**"Didn't return a usable verification URL"** means the backend has no `FRONTEND_URL` set. The operator must set it to the public frontend address. See [Configuration](../technical/configuration.md).

## The agent edits the wrong files

Check **Project Settings → General** for the repository path. The worktree is created from it.

For a multi-repository project, also confirm the task declares the repository you expect.

## The Stop button appears to do nothing

The daemon may have restarted. On the next dispatch it finds no in-flight entry, so the cancel becomes a no-op, but the run record still exists.

Mark the run cancelled from the run page.

## Runs stay queued and never start

The daemon caps concurrent runs. Stale runs holding slots make an agent look permanently busy.

Open the run list, find runs stuck in a ready or running state whose daemon is gone, and discard them. A periodic sweep also reconciles these, but discarding is immediate.

## A run reports success but produced nothing

Open the run and check the diff and artifacts.

An empty diff with no artifacts and a `succeeded` outcome means the agent described work rather than doing it. This is a real failure mode, particularly with runtimes that cannot call MCP tools — the agent narrates tool use as prose instead.

Check the runtime's capabilities:

```bash
agentira runtime list
```

A runtime without MCP support cannot register artifacts or declare outcomes, however capable the model is.

## Resume fails with "no conversation found"

Rare. Send another message — the daemon retries once without resuming and the agent picks up from stored history.

## Attachments disappear after a redeploy

The backend's data directory is not on a persistent volume. Mount one. See [Deployment](../technical/deployment.md).

## Tasks will not move between columns

Gates are enabled and the required evidence is missing. The interface names the failing gates.

Common causes:

- The definition of done has unchecked items
- No pull request is linked
- No structured reviewer verdict is recorded — a comment saying "approved" does not count
- A provider answered `unknown` because its credentials are not configured, and unknown blocks

See [Evidence gates](./gates.md).

## Getting help

Search the [issue tracker](https://github.com/gitmaster3000/agentira-oss/issues) first. If you open an issue, include:

- What you did, what you expected, what happened
- Relevant output from `agentira daemon logs`
- Your runtime list
- Whether you are running locally or on a hosted deployment

Do not report a security vulnerability publicly. See [Contributing](../contributing/index.md).
