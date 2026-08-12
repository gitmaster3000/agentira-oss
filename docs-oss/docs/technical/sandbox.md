---
id: sandbox
title: Sandbox resolution
sidebar_label: Sandbox
---

# Sandbox resolution

Sandbox modes declare how much of the host an agent may touch.

:::danger Not a security boundary
Modes are configured, resolved, and logged. They are **not enforced per runtime**. An agent can reach whatever the daemon's user account can reach.

Do not rely on a sandbox mode to contain untrusted work. Per-runtime enforcement is on the roadmap.
:::

## Modes

| Mode | Intent |
|---|---|
| `off` | No containment |
| `cwd` | Confine to the working directory |
| `strict` | Confine with a reduced capability set |
| `container` | Run inside a container |

## Resolution order

Implemented in `backend/sandbox.py`:

1. Start from the agent's default mode.
2. Apply the project mode, which overrides it.
3. Downshift to what the selected runtime supports.
4. Write the resolved mode to the dispatch log.

The log line is authoritative. The configured value and the applied value can differ when the runtime cannot support the request.

## Planned enforcement

| Platform | Mechanism |
|---|---|
| Linux | bubblewrap |
| macOS | `sandbox-exec` |
| Any | Container per agent |

An audited escape-hatch tool for deliberate access outside the sandbox is also planned, so that legitimate cases are visible rather than achieved by disabling containment.

## Operating safely today

**Run the daemon as a dedicated user** with access only to the repositories agents should touch. This is the strongest control currently available, and it is enforced by the operating system rather than by Agentira.

**Isolate agent repositories** from credentials, personal files, and unrelated work.

**Use branch protection** so an agent cannot push to a branch that matters.

**Review diffs before merging.** The diff is captured from Git and cannot be overstated by the agent.

**Keep no real credentials in reachable repositories.**

## Environment isolation

Separate from sandboxing, Agentira supports per-run environment setup and teardown:

| Variable | Purpose |
|---|---|
| `AGENTIRA_ENV_ISOLATION` | Isolation strategy |
| `AGENTIRA_ENV_SETUP_CMD` | Command run before the agent starts |
| `AGENTIRA_ENV_SETUP_TIMEOUT` | Setup timeout |
| `AGENTIRA_ENV_TEARDOWN_CMD` | Command run after the agent finishes |
| `AGENTIRA_ENV_TEARDOWN_TIMEOUT` | Teardown timeout |
| `AGENTIRA_ENV_DB_ADMIN_URL` | Administrative database address for per-run databases |

Use these to give each run a scratch database or a prepared workspace. They control the environment the agent works in, not what it may reach.

## Reporting an escape

Do not open a public issue. See the security section of [Contributing](../contributing/index.md).
