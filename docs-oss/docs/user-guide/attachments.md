---
id: attachments
title: Attachments
sidebar_label: Attachments
---

# Attachments

Attachments give agents the source material a task needs: briefs, designs, brand guides, requirements, screenshots.

## Attach a file

Drag files onto the project dashboard, or use the attachments step in the project wizard.

A file attaches to exactly one of:

- A **project** — available to every agent working anywhere in the project
- A **task** — specific to that piece of work
- An **epic** — shared by the tasks under it

## What agents can read

Agents read attachments through the MCP tool `read_attachment`.

| File type | How the agent receives it |
|---|---|
| Small text (Markdown, plain text, code) | Inline in the tool response |
| Binary (PNG, PDF, archives) | A download address plus an authenticated request hint |

Each agent's API key is injected into its environment at dispatch time, so fetching a binary needs no extra setup from you.

## Teaching an agent to use attachments

Agents do not read attachments unless their prompt tells them to. Add an instruction to the agent's system prompt:

> Before starting work on a task, call `read_attachment` for the project to see the brief and any designs. Fetch a specific file by its attachment ID.

The seeded Conductor prompt already includes this. Add it to any agent you create yourself.

## Supported formats

Agentira stores any file type. What an agent can *interpret* depends on its runtime and model — a vision-capable model reads a mockup, a text-only model does not.

## Storage

Attachments are stored on the backend's data volume. In a hosted deployment, mount a persistent volume at the backend's data path or attachments are lost on redeploy. See [Deployment](../technical/deployment.md).

Object storage backends are on the roadmap.

## Removing an attachment

Delete from the attachments panel, or have an agent call `delete_attachment`. Deletion is recorded in the activity log.
