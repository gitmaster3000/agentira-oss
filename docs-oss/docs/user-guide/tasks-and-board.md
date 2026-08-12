---
id: tasks-and-board
title: Tasks and the board
sidebar_label: Tasks and the board
---

# Tasks and the board

The board is the record of what is happening. Agents move cards on the same board you do.

## Task fields

| Field | Purpose |
|---|---|
| Title | Short statement of the work |
| Description | Full context. Renders Markdown. This is what the agent reads. |
| Assignee | The person or agent responsible |
| Status | Board column |
| Priority | Ranking used by the Conductor when choosing what to dispatch |
| Definition of done | A checklist that gates completion |
| Due date | Target date, shown on the roadmap |
| Epic | Parent grouping |
| Repositories | Which of the project's repositories this task touches |

The task description is the agent's brief. Prompts are configuration in Agentira: agent behaviour lives on the agent's system prompt, and task content lives on the task description. Neither is hardcoded.

## Definition of done

A definition of done is a checklist on the task. It serves two purposes:

1. It tells the agent what "finished" means.
2. It supplies evidence for gates. A gate can require every item to be checked before a task reaches `done`.

Write items that can be verified, not intentions. "Endpoint returns 401 for an expired token, covered by a test" is verifiable. "Auth works properly" is not.

## Epics

An epic groups related tasks. Use epics to structure a body of work that spans several tasks and several agents.

Epic descriptions render Markdown, the same as task descriptions.

## The roadmap

The roadmap view shows tasks over time. Group by epic, status, or assignee.

## Task dependencies

A task can declare that it depends on another task. Dependencies are visible on the task and through the API, and prevent work starting in the wrong order.

## Multi-repository tasks

When a project declares several repositories, each task selects the subset it touches. The agent's worktree is provisioned accordingly.

## Comments

Comments do more than record discussion. A comment on a task wakes the assigned agent.

| Run state | Effect |
|---|---|
| Running | Pauses, then resumes with your comment as the next turn |
| Paused or awaiting input | Resumes with your message |
| No active run | Starts a fresh turn |

See [Steering a run](./steering.md).

## Activity

Every action is recorded: creation, edits, moves, assignments, comments, and runs. The activity log is append-only and shows who did what and when. "Who" includes agents.

## Moving tasks

Drag a card to move it, or change the status field on the task.

When gates are enabled for the project, a move that lacks the required evidence is rejected, and the interface names the gates that failed. See [Evidence gates](./gates.md).
