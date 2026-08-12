---
id: intro
title: What Agentira is
sidebar_label: What Agentira is
sidebar_position: 1
slug: /
---

# What Agentira is

Agentira is a self-hosted platform for running AI coding agents against real software projects.

You do not chat with a single model. You run a small team of agents — a planner, implementers, a reviewer, an orchestrator — against your repositories. Every piece of work produces a traceable run, verifiable artifacts, and a board position that reflects what actually happened.

## Who it is for

Agentira targets founders, small software teams, and solo builders who want throughput. You do not need to be a Git or infrastructure expert to use it. Technical internals stay behind an optional **Advanced** reveal in the interface.

## What makes it different

Interactive coding tools work well while you watch the screen. Agentira is built for the hours you are not watching.

The trade is deliberate:

| You give up | You get |
|---|---|
| Approving every keystroke | Every run produces evidence you can inspect |
| Immediate manual correction | Every board transition passes a gate |
| A single chat transcript | A board that reflects real state |

## How the pieces fit

Agentira has four layers. The first two run wherever you host them. The last two run on your own machine, because that is where your code is.

```
Browser
  │  HTTPS / WebSocket
Backend — REST API for people, MCP server for agents, gate engine
  │  WebSocket dispatch
Daemon — receives work, owns Git worktrees and logs
  │  subprocess
Runtime — Claude CLI, Codex, Grok, Ollama, and others. Edits files. Commits. Opens pull requests.
```

The backend coordinates. Your machine executes. Nothing in a self-hosted deployment depends on a service the maintainers control.

## The shape of a work cycle

1. You create a project and attach a brief, a design, or both.
2. The Conductor agent reads the brief, chooses a stack, and breaks the work into 3–8 tasks.
3. You assign each task to the agent best suited to it.
4. You select **Run**. The agent works in its own Git worktree, commits, and opens a pull request.
5. You inspect the run: status, diff, artifacts, conversation, token cost.
6. You comment to steer, or move the task onward if it passes its gates.

## Where to go next

| If you want to | Read |
|---|---|
| Get Agentira running | [Install Agentira](./user-guide/install.md) |
| Work through a first project | [Your first project](./user-guide/first-project.md) |
| Understand the internals | [Architecture](./technical/architecture.md) |
| Connect your own agent | [MCP server](./technical/mcp-server.md) |
| Contribute code | [Contributing](./contributing/index.md) |

## Project status

Agentira works, self-hosts, and is used to build itself. It is also early. Expect rough edges where a small project has them: daemon installation is manual, sandbox enforcement is configured but not yet enforced per runtime, and documentation lags the code in places.

What is solid: the stack boots from a clean clone, and the full loop — board to task to dispatch to runtime to pull request — works end to end.

Agentira is licensed under [Apache-2.0](https://github.com/gitmaster3000/agentira-oss/blob/main/LICENSE).
