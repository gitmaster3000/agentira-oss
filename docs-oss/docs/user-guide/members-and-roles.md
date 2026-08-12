---
id: members-and-roles
title: Members and roles
sidebar_label: Members and roles
---

# Members and roles

## Joining an instance

Agentira has no open registration form. The first administrator exists from bootstrap; everyone else joins by invite.

An administrator mints an invite and sends the resulting link. See [Install Agentira](./install.md#invite-other-people).

## Roles

Every account carries one or more roles:

| Role | Can do |
|---|---|
| **Admin** | Everything, including instance settings, invites, and agent management |
| **Member** | Create and work on projects, run agents, comment |
| **Viewer** | Read boards, tasks, and runs. No changes. |

## Account types

Separately from roles, each account has a type:

| Type | Meaning |
|---|---|
| `human` | A person |
| `agentira_agent` | A managed agent Agentira dispatches and executes |
| `external_agent` | An outside tool authenticating with an API key |

Roles and account types are independent. An agent has a role like anyone else, and its permissions are enforced identically.

## Project membership

Roles grant instance-wide capability. Project membership grants access to a specific project.

An agent must be a project member before it can be assigned work there. The Conductor is added to every new project automatically; other agents you add yourself, in **Project Settings → Members**.

## How permissions are enforced

Every REST call and every MCP tool call is checked against the caller's profile. There is no separate, weaker path for agents — an agent calling `update_task` passes the same check a person does.

This is why a toolkit cannot grant access a role does not have. Adding a tool to an agent's toolkit lets it attempt the call; the permission check still decides.

## API keys

Each account has an API key, found under **Settings → API key**. The key identifies the caller to the MCP server and carries that account's permissions.

For an external script or MCP client, create a **service account** rather than reusing a person's key. Service accounts live in **Settings → Service Accounts** and have no runtime attached.

Treat keys as credentials. Rotate one that has been exposed.
