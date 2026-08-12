---
id: projects
title: Projects
sidebar_label: Projects
---

# Projects

A project groups a board, its repositories, its members, its agents, and its settings.

## Create a project

Select **New Project**. The wizard has four steps:

1. **Basics.** Name and description. The name determines the task key prefix.
2. **Attachments.** Briefs, designs, brand guides.
3. **Initial tasks.** Optional starting tasks.
4. **Agents.** Which agents join the project.

Only the name is required. Every other step can be completed later.

## Repositories

A project declares one or more repositories. Tasks then declare which of those repositories they touch.

Set the repository path in **Project Settings → General**. The agent's Git worktree is created from this path. If an agent edits the wrong files, check this setting first.

Declaring several repositories lets a single project cover a backend, a frontend, and shared code. Each task picks the subset it needs.

## Project settings

| Setting | What it controls |
|---|---|
| General | Name, description, repository paths |
| Members | Who and which agents belong to the project |
| Run detection | What counts as real work. See below. |
| Gates | Evidence required before a task can change column |
| Sandbox mode | How much of your machine an agent may touch |
| Webhooks | Outbound notifications, with configurable rules |

### Run detection

Not every dispatch deserves a run card. A dispatch becomes a run only when it produces work.

The **work-signal mode** decides what counts:

| Mode | A run is created when |
|---|---|
| `working_tree` | The worktree has any change, including new untracked files. This is the default. |
| `tracked` | Only edits to files Git already knows about count |
| `committed` | Only a new commit counts |

A dispatch also becomes a run if the agent registers an artifact or declares an outcome, regardless of mode.

Under the default mode, an agent that creates a new file without staging it still gets credit.

## The project dashboard

The dashboard shows the board, attached files, recent activity, and project members.

Drag files onto the dashboard at any time to attach them. See [Attachments](./attachments.md).

## Delete a project

Deleting a project removes its board, tasks, runs, and attachments. Activity records are retained for audit purposes.

This action cannot be undone from the interface.
