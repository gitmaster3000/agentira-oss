---
id: daemon
title: Connect the daemon
sidebar_label: Connect the daemon
---

# Connect the daemon

The daemon is the bridge between the Agentira backend and the coding runtime that does the work. It runs on your own machine.

## Why it runs locally

Agents edit real files in real Git repositories. Those repositories live on your machine. The backend coordinates the work; the daemon executes it.

## Install the daemon

```bash
pip install -e agentira-cli/
```

## Authorise the daemon

```bash
agentira daemon login --api-url http://localhost:8111
```

This opens your browser at the instance's `/cli-auth` page. Approve the daemon while signed in as an administrator. The token is stored in `~/.agentira/credentials.json`.

You never paste an API key.

## Start the daemon

```bash
agentira daemon start
```

Expected output:

```
✓ Daemon authorized. You can now run `agentira daemon start`.
Daemon started (PID 58194) — home /Users/you/.agentira
WS connected + registered to ws://localhost:8111/api/forge/daemon/ws
```

The daemon connects over WebSocket, registers every runtime it finds on your `PATH`, and waits for work.

:::note
`agentira daemon` on its own is a command group, not a command. Use `login` first, then `start`.
:::

## Check the daemon

```bash
agentira daemon status
agentira daemon logs
agentira runtime list
```

`agentira runtime list` shows which runtimes the daemon detected and what each one supports.

## Manage the daemon

The daemon moves itself to the background. Closing the terminal does not stop it.

| Command | Effect |
|---|---|
| `agentira daemon start` | Start the daemon |
| `agentira daemon stop` | Stop the daemon |
| `agentira daemon status` | Show connection state |
| `agentira daemon logs` | Show the daemon log |
| `agentira daemon update` | Upgrade to the latest published CLI |
| `agentira daemon install-launchd` | On macOS, restart on crash and at login |

## Development shortcut

For a local stack you can skip the browser approval. The development Compose profile ships a static daemon key:

```bash
AGENTIRA_DAEMON_API_URL=http://127.0.0.1:8111 \
AGENTIRA_DAEMON_API_KEY=dev-daemon-key-local-only \
  agentira daemon start
```

This shortcut requires `AGENTIRA_ENV=dev` on the backend. It does nothing in any other environment.

## Troubleshooting

**The daemon cannot find a runtime.** Install one and confirm it is on your `PATH`. For the Claude CLI:

```bash
npm i -g @anthropic-ai/claude-code
```

**Login reports "didn't return a usable verification URL".** The backend has no `FRONTEND_URL` set. This is an operator fix — see [Configuration](../technical/configuration.md).

**The daemon connects but no work arrives.** Confirm the WebSocket registered by checking `agentira daemon logs`. Then confirm your agent is a member of the project.

## Next step

Continue to [Your first project](./first-project.md).
