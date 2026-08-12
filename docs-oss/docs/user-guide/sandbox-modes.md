---
id: sandbox-modes
title: Sandbox modes
sidebar_label: Sandbox modes
---

# Sandbox modes

A sandbox mode declares how much of your machine an agent may touch.

:::warning Enforcement is not complete
Sandbox modes are configured, resolved, and logged today. They are **not yet enforced per runtime**. An agent can currently reach whatever your user account can reach.

Treat the setting as a declaration of intent, not a security boundary. Per-runtime enforcement is on the roadmap.
:::

## The modes

| Mode | Intent |
|---|---|
| `off` | No containment |
| `cwd` | Confine the agent to its working directory |
| `strict` | Confine to the working directory with a reduced capability set |
| `container` | Run the agent inside a container |

## How a mode is chosen

Two settings combine:

1. **The agent's default mode**, on the agent's own settings.
2. **The project's mode**, in Project Settings.

The project mode overrides the agent default. The resolver then downshifts to whatever the selected runtime actually supports, and the resolved mode is written to the dispatch log.

That log line is the authoritative record of what was requested. Read it rather than assuming the configured value applied.

## Running Agentira safely today

Until enforcement lands, contain the blast radius by other means:

**Run the daemon as a dedicated user account** with access only to the repositories you want agents touching.

**Keep agent repositories separate** from anything containing credentials, personal files, or unrelated work.

**Review diffs before merging.** The diff on the run page is captured from Git and cannot be overstated by the agent.

**Do not store real credentials in repositories agents can reach.** This is good practice regardless.

**Use branch protection** on any branch that matters, so an agent cannot push directly to it.

## Reporting a problem

If you find a way an agent escapes its declared mode, do not open a public issue. See the security section of [Contributing](../contributing/index.md).
