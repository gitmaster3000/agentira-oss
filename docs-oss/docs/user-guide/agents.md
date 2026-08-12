---
id: agents
title: Agents
sidebar_label: Agents
---

# Agents

An agent is a configured worker: a persona, a model, a toolkit, and a set of permissions.

## The seeded agents

Every fresh installation includes seven agents:

| Agent | Role |
|---|---|
| **Conductor** | Orchestrator. Plans projects, breaks down work, and can dispatch tasks on its own. |
| **Planner** | Turns vague tasks into concrete definitions of done and child tasks. |
| **Backend Implementer** | Server-side engineering. |
| **Frontend Implementer** | Interface engineering. |
| **Reviewer** | Checks work against the definition of done. Does not approve unverified progress. |
| **DevOps** | Containers, continuous integration, deployment. |
| **Guide** | Answers questions about Agentira itself. |

These are starting points. Every prompt is yours to edit.

## Agent settings

| Setting | Purpose |
|---|---|
| Name | How the agent appears on the board |
| Model | Which model the runtime uses |
| System prompt | The persona and standing instructions |
| Toolkit | Which MCP tools the agent may call |
| Runtime | Which coding tool executes the work |
| Sandbox mode | Default containment level |

### The system prompt

The system prompt defines the agent. It is configuration, not code — edit it in the interface, and your edit is authoritative.

Agentira seeds default prompts only when the field is empty. Your edits are never overwritten by an upgrade.

A useful prompt states the role, the standards, and the reporting expectations:

> You are a senior backend engineer working in Python and PostgreSQL. Write the failing test before the implementation. Register a pull request artifact before you finish. If the task is ambiguous, finish with `needs_input` and one specific question rather than guessing.

### Toolkits

Each agent has an MCP toolkit — the set of tools it may call. Every call is checked against the agent's permissions, so a toolkit cannot grant access the agent's role does not have.

See the [MCP tool reference](../technical/mcp-tools.md).

## Create an agent

1. Open the agents page and select **New Agent**.
2. Set a name, a model, and a system prompt.
3. Choose a runtime, or leave the default.
4. Add the agent to the projects it should work on.

An agent must be a project member before it can be assigned work in that project.

## Agent templates

Default agents come from template files in `templates/agents/`, as YAML and Markdown pairs. Add your own template files and restart to have them seeded.

Seeding sets a field only when it is empty, so templates never overwrite edits you have made.

## Service accounts and managed agents

Agentira separates two kinds of non-human identity:

| Kind | Has a runtime | Where it lives | Use for |
|---|---|---|---|
| **Managed agent** | Yes | Agents page | Work Agentira dispatches and executes |
| **Service account** | No | Settings → Service Accounts | External tools calling the API with a key |

Use a service account when you want your own script or an external MCP client to read and write the workspace. Use a managed agent when you want Agentira to run the work.

## Runtimes

The runtime is the tool that actually edits code. The daemon detects whichever runtimes are installed on your machine.

Supported runtimes include the Claude CLI, Codex, Grok, Gemini, OpenCode, OpenClaw, and Ollama.

Runtimes differ in what they support. A runtime without resume support cannot continue a paused session; Agentira degrades to the closest available behaviour rather than failing. See [Runtimes](../technical/runtimes.md).

Check what is available:

```bash
agentira runtime list
```
