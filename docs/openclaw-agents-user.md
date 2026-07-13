# Using OpenClaw agents in Flowty (user guide)

**Audience:** founders and team leads connecting an OpenClaw-powered agent  
**Keep it plain:** you do not need to know OpenClaw’s internals.

## What you get

When an agent’s **runtime** is **OpenClaw**:

- The agent can **use tools** (read and change files, run commands) on the machine where your Agentira daemon runs.
- Flowty still owns **who the agent is** (name, instructions, memory) and **which project folder** it works in.
- OpenClaw is the **engine** under the hood — not a second personality.

## Before you start

1. **OpenClaw** installed and the gateway running on the agent machine (default port `18789`).
2. **Agentira daemon** installed and online (`agentira daemon status`).
3. Pairing once if prompted: `agentira daemon pair` (gives the daemon permission to run agent turns).

You do **not** paste OpenClaw’s secret tokens into Flowty for normal chat — the daemon handles that.

## Create / configure the agent

In **Forge → Agents →** your agent → settings:

| Setting | What to put |
|---------|-------------|
| Runtime | **OpenClaw** |
| Model | A model OpenClaw can reach (for example an Ollama model name) |
| System prompt | How you want **this** agent to behave (product owner language is fine) |
| Tools / MCP | Leave Agentira tools on; optional extras as needed |

You do **not** need to create a matching “persona” agent inside OpenClaw’s own UI. Flowty creates a private engine slot for this agent automatically.

## How work folders work

When the agent works a **task**:

1. Flowty prepares a **desk** for that task (including multi-repo layouts like `frontend/` + `primary/`).
2. That desk is handed to the engine so tools see the **real project**, not a random OpenClaw home folder.
3. One agent works **one task at a time** — when they switch tasks, the desk switches too.

If the task is a UI bug, the agent should see the frontend folder on that desk. If it claims “I only see a CLI package,” the workspace binding failed — check daemon logs or re-dispatch the run.

## Chat, resume, clear

- **Chat** on a task or with the agent continues the same thread when possible.
- **Clear** starts a fresh thread for that conversation (old resume handle is dropped).
- **Cancel** stops the current run.

## What success looks like

- Board shows the agent **running** while tools work.
- Chat shows text (and tool lines when the stream is healthy).
- The agent can open files under the task desk and open a PR on the task branch.

## Troubleshooting (plain language)

| You see | Try |
|---------|-----|
| “missing scope: operator.write” | On the agent machine: `agentira daemon pair` then restart the daemon. |
| Agent only talks about the wrong folder | Re-run the task; confirm the project has the right repos attached. |
| Model / connection errors | Start Ollama (or your model provider) and check OpenClaw’s model list. |
| Session locked | Wait a few seconds and retry; or restart OpenClaw gateway. |

## Privacy note

Flowty does not use your personal OpenClaw “main” agent identity for product agents. Engine slots are separate and carry empty system overrides so your OpenClaw home persona does not leak into Flowty agents.

## Advanced / technical

Session keys, engine ids (`ar-…`), and config paths: see [openclaw-engine-agents.md](./openclaw-engine-agents.md).
