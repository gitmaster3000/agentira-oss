# Agent Conversations

How memory works for chats and runs.

## The mental model

Every agent has separate **conversations** — one per context. A conversation is
the agent's working memory: what was said, what tools were used, what files were
touched. Each conversation is a separate "slot" in the agent's brain.

The active conversation is shown at the top of the chat panel (the picker).

## Conversation types

There are three kinds of conversations. The picker labels each one.

| Label | When it's used | Identifier |
|---|---|---|
| **General** | Free-form chat, no project context | `chat:default` |
| **About \<Project\>** | Chat scoped to a specific project | `chat:project:<project>` |
| **Task \<title\>** | All runs and follow-ups for a specific task | `task:<task>` |

Each is independent. The agent's memory in General does not leak into a project
chat or a task. Different agents working on the same task have separate
memories.

## Re-running a task

Click **Run** on a task → the agent works on it. Close the run, come back
tomorrow, click Run again → the agent **picks up where it left off**. Same
task, same conversation, accumulating memory across attempts.

This is different from how it used to work (each run was a separate
conversation). The change is described in [ADR 008].

## Multiple agents on the same task

If two different agents work on the same task, they each have their own memory
of it. They don't share what they tried. This is intentional — you can compare
two agents' approaches by reading their separate conversations.

## Controls

### `/clear` — wipe the active conversation

Type `/clear` in the chat input. Confirms, then drops:

- The agent's memory of this conversation (runtime session handle).
- All visible messages in this conversation.

Does NOT touch run rows, diffs, or task comments. Just the agent's working
memory for this scope.

### Stop button — interrupt a dispatch in progress

Visible during an active dispatch. Clicking it:

- Cancels the in-flight subprocess gracefully.
- If the chat is in a task scope AND a run is running for that task →
  **pauses the run**. (The Run row's status flips to PAUSED.)
- The agent's memory is preserved.

### Sending a message into a paused run = automatic resume

If the run is paused and you send a new message:

- The run flips back to RUNNING.
- The agent resumes with full prior context (claude `--resume`).
- Your message becomes the next user turn.
- A "Resumed paused run" badge appears so you know.

### Pause / Resume on Run detail page

For direct control without the chat: explicit Pause and Resume buttons on
the Run detail page. Same effect as the chat-Stop / chat-message-after-pause
flow.

## Cross-project context (the `+` button)

The `+` button next to the chat input attaches a project as **reference context**.
It does NOT switch conversations. Use case: "I'm chatting about Project A, but
this question also needs to know about Project B's structure." The reference
flows in `user_context.references[]` and is read by the agent's MCP tools.

## What's NOT supported (yet)

- Multiple chat threads per (agent, project). Hold one conversation per scope.
- Cross-project unified chat — each project is its own context.
- @mention to dispatch an agent from a task comment. Tracked separately.
- Cross-machine conversation resume — claude's session is local to its host.

## See also

- [ADR 008] — architectural decisions behind these scopes
- AP-94 — cross-machine resume
- AP-95 — `/clear` (now part of AP-93)
- AP-96 — @mention dispatch

[ADR 008]: ./architecture_decision_record.md
