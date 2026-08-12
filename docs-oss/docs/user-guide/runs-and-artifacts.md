---
id: runs-and-artifacts
title: Runs and artifacts
sidebar_label: Runs and artifacts
---

# Runs and artifacts

## The run page

The run page is the evidence record for one work episode.

| Panel | What it shows |
|---|---|
| Status | Current state and final outcome |
| Conversation | Prompts, tool calls, tool results, and replies, streaming live |
| Diff | Every file the agent changed |
| Artifacts | Concrete deliverables the agent registered |
| Accounting | Tokens consumed and estimated cost |
| Events | The raw event stream, for diagnosis |

## Artifacts

An artifact is a deliverable the agent registered deliberately. It answers "what did this run actually produce?"

| Kind | Contents |
|---|---|
| `pr` | A pull request |
| `commit` | A specific commit |
| `file` | A key file the run produced |
| `report` | A Markdown report |
| `url` | A deployed or preview address |
| `log` | A relevant log file |

Artifacts are capped and deduplicated, so a talkative agent cannot flood the panel.

### Why artifacts matter

**The conversation transcript is not an artifact.** If an agent writes a plan in chat and never registers it, the person reading the run next week will not find it.

The seeded agent prompts instruct agents to register artifacts. If an agent of yours forgets, add the instruction to its system prompt.

## The diff

The diff shows what changed in the worktree. It is captured from Git, not reported by the agent, so it cannot be overstated.

An empty diff on a run that claims success is worth investigating. It usually means the agent described work rather than doing it.

## Accounting

Each run records token consumption and estimated cost, broken down by turn. Use it to find agents whose prompts have grown expensive.

## Reading a run critically

Agentira is built so you can verify claims rather than trust them. When reviewing:

1. Compare the diff against the definition of done.
2. Confirm the artifacts exist and open correctly.
3. Check the outcome matches the evidence. An agent that declares success with no diff and no artifacts has done nothing.
4. Read the final turns of the conversation for hedging or unverified claims.

This scepticism is the point. Gates automate parts of it — see [Evidence gates](./gates.md).
