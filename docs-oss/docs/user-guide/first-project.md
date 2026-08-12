---
id: first-project
title: Your first project
sidebar_label: Your first project
---

# Your first project

This walkthrough takes you from an empty workspace to an agent opening a pull request.

Before you start, confirm the stack is running ([Install Agentira](./install.md)) and the daemon is connected ([Connect the daemon](./daemon.md)).

## 1. Create the project

Select **New Project**. Complete the wizard:

- **Name.** The first letters become the prefix for task keys. "Voice Code App" produces `VCA-1`, `VCA-2`, and so on.
- **Description.** One or two paragraphs describing what you want built. The Conductor reads this, so be specific.
- **Attachments.** Drop in designs, mockups, briefs, or requirements. PNG, PDF, and Markdown all work. Files attach to the project itself.
- **Initial tasks and agents.** Optional. You can set both later.

Select **Create**.

## 2. Confirm what was created for you

Immediately after creation:

- The Conductor is a project member.
- A task named **Plan this project** sits in the `todo` column, assigned to the Conductor.
- Your uploaded files appear on the project dashboard under **Attachments**.

You configured none of that.

## 3. Run the kickoff task

Open **Plan this project** and select **Run**.

The Conductor performs five steps:

1. Reads the project description and any attachments.
2. Chooses tools and a technology stack, with a short justification for each choice.
3. Writes a one-page plan covering architecture, milestones, and risks, and registers it as an artifact.
4. Breaks the work into 3–8 child tasks, each with a title, description, and definition of done.
5. Declares an outcome.

### What you see while it runs

| Panel | What it shows |
|---|---|
| Status badge | `pending` → `running` → `completed` |
| Conversation | The prompt, tool calls, tool output, and final reply, streaming live |
| Artifacts | The registered plan |
| Diff | Empty for this run — the Conductor edits no code |
| Tokens and cost | Rising as the run proceeds |

When the run completes, your board holds 3–8 new tasks.

### If the brief was too vague

The Conductor finishes with the outcome `needs_input` and a specific question. Comment on the task to answer. Your comment resumes the run with your answer as the next turn.

## 4. Assign the work

For each new task, set **Assignee** to the agent suited to it. Use the Backend Implementer for API work, the Frontend Implementer for interface work, and so on.

To create a different agent, see [Agents](./agents.md).

## 5. Run a task

Select **Run** on an assigned task. The agent:

1. Receives the dispatch on your machine.
2. Works inside its own Git worktree for the project repository.
3. Edits files, commits, and opens a pull request if it is able.
4. Registers artifacts and declares an outcome.

## 6. Steer the work

Comment on the task at any time. What happens depends on the run state:

| Run state | Effect of your comment |
|---|---|
| Running | Pauses the run, then resumes it with your comment as the next turn |
| Paused, blocked, or awaiting input | Resumes the run with your message |
| Finished | Starts a fresh turn |

This is the primary way you direct an agent. See [Steering a run](./steering.md).

## 7. Review the result

Open the run and check the **Artifacts** panel. This answers the question "what did this agent actually produce?"

The conversation transcript is not an artifact. If an agent describes a plan in chat but never registers it, nobody reading the run tomorrow will find it.

See [Runs and artifacts](./runs-and-artifacts.md).

## What to read next

- [Tasks and the board](./tasks-and-board.md) — epics, priorities, definitions of done
- [Evidence gates](./gates.md) — enforce evidence before a task can move
- [The Conductor](./conductor.md) — let the orchestrator dispatch work on its own
