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

### Connecting other apps (MCP servers)

Admins connect an app once in **Build → MCP Servers**: pick **Add Ezine** or **Add a server**, then **Connect & find tools**. Your daemon contacts the server from your machine (the same place agents run), lists its tools and shows whether it connected, so the status matches what agents will actually get. If no daemon is online the page says so instead of guessing. **Test** refreshes the list. The same page lists apps already set up on your machine under **On this machine**, with the same check.

A connected server with the same name as one on your machine replaces it for agents; the page warns when that happens.

Each server signs in one of three ways: the agent's own Agentira login (Ezine uses this, so no secret is stored), a token you paste (stored encrypted, never shown again), or no login.

Tick an agent's name under a server on that page (or click the server's chip in the agent's Config tab) to switch it on for that agent. Its tools appear underneath; untick any the agent should not use. If the server marks tools as read-only, only those start ticked. Unticked tools are removed from the agent's session (`--disallowedTools`), not just discouraged. Tools added to the server later stay allowed until you narrow the list again, so press **Test** after a server changes.

Only remote (HTTP) servers can be added here. Local command-line servers can still be set through the agent's advanced JSON override.

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

## Agents asking each other for help

Agents can message one another directly. For example, an implementer can ask the reviewer a quick question, or hand a task over when its part is done. You do not have to relay anything.

When the question is about a task, a short line shows up on that task's feed ("implementer-1 asked reviewer: …"), so you can follow along from the board. If the other agent is busy, the message waits and is delivered when it finishes its current work. Agents can only reach agents in your own workspace, never themselves, and no more than 30 messages per conversation per hour.

See [Agent-to-agent messaging](../technical/a2a.md) for how it works.

## Runtimes

The runtime is the tool that actually edits code. The daemon detects whichever runtimes are installed on your machine.

Supported runtimes include the Claude CLI, Codex, Grok, Gemini, OpenCode, OpenClaw, and Ollama.

Runtimes differ in what they support. A runtime without resume support cannot continue a paused session; Agentira degrades to the closest available behaviour rather than failing. See [Runtimes](../technical/runtimes.md).

Check what is available:

```bash
agentira runtime list
```

## Connect from Claude (custom connector)

An admin opens the agent in Settings and clicks **Copy connector link**. In Claude, add a custom connector and paste that link (it looks like `https://<your-mcp-service>/mcp?as=<agent>`). Leave the client ID and secret empty. Claude opens an Agentira sign-in page; an admin signs in with their normal username or email and password and the connection acts as that agent. Without `?as=`, admins choose who the connection acts as; non-admins always act as themselves. No API key or header needed. Static API keys still work for IDEs and bots. Clients that identify themselves with a client metadata URL (for example Claude Code and ChatGPT) are accepted too; see [Clients that use a metadata URL](#clients-that-use-a-metadata-url). If you are already signed in to Agentira in the same browser, the sign-in page can be skipped (needs `MCP_SSO_FRONTEND_URL`, see Configuration); you go straight to choosing who the connection acts as.

The MCP service must share `JWT_SECRET` with the backend. Tokens last one hour and renew automatically.

## Connect from ChatGPT or the OpenAI API

ChatGPT works with the same MCP address. In ChatGPT, add a custom MCP connector (Developer mode), paste the link (`https://<your-mcp-service>/mcp`, or the agent link from **Copy connector link**) and choose OAuth. ChatGPT registers itself, then opens the Agentira sign-in page; sign in and choose who the connection acts as, exactly as with Claude. Leave any client ID and secret empty.

- ChatGPT registers itself like any other client; its return address and the `iss` value it checks on the sign-in response are handled. No setting is needed.
- ChatGPT cannot use static API keys. For the OpenAI API (Responses API `mcp` tool) or the Agents SDK, pass an Agentira API key as the tool's `authorization` value instead of using OAuth.

### Clients that use a metadata URL

Some clients (Claude Code, ChatGPT) can use a web address as their client ID and publish their return addresses there, instead of registering. The MCP service accepts this from any host, with no list to maintain. Safeguards:

- The address must be `https` on the standard port, with no user name, password or fragment.
- The host must resolve only to public addresses. Loopback, private, link-local and other internal addresses are refused, and the service connects to the address it checked.
- No redirects, a 5 second limit, and a 64 KB limit. The document's own `client_id` must equal the address.
- The sign-in page only returns to an address listed in the document (a `localhost` return address may use any port, since native apps pick a free one).
- Results are cached for an hour (a failure for a minute). Nothing is stored.

This is accepted but not advertised in discovery, so clients that register themselves keep doing so exactly as before.
