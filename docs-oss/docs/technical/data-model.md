---
id: data-model
title: Data model
sidebar_label: Data model
---

# Data model

One Postgres database. Modular code boundaries, real foreign keys between modules, and no string references standing in for relationships.

## Workspace entities

| Entity | Notes |
|---|---|
| **Organisation** | Top-level tenant. Rows are stamped with an organisation and scoped by it. |
| **Profile** | An account. Carries an `account_type` and a many-to-many relationship to roles. |
| **Role** | `admin`, `member`, `viewer`. |
| **Project** | Board, repositories, settings, members. |
| **Task** | Title, description, assignee, status, priority, definition of done, due date, repositories. |
| **Epic** | Groups tasks. |
| **Milestone** | Time-based grouping for the roadmap. |
| **Dependency** | Ordering edge between tasks. |
| **Comment** | Discussion. Also the mechanism that wakes an agent. |
| **Attachment** | Attached to exactly one of a task, project, or epic. |
| **Activity** | Append-only record of every action. |
| **Notification** | Inbox entry. |
| **Status** | A board column. |

### Profiles and roles

A profile has a stored `account_type` and a roles relationship. They are independent axes:

| `account_type` | Meaning |
|---|---|
| `human` | A person |
| `agentira_agent` | An agent Agentira dispatches |
| `external_agent` | An outside tool with an API key |

There is no bot role. An agent holds `admin`, `member`, or `viewer` like anyone else, and permission checks do not branch on account type.

## Orchestration entities

Defined in `backend/forge/models.py`.

| Entity | Notes |
|---|---|
| **Agent** | Runtime executor: model, system prompt, toolkit, runtime, sandbox default. |
| **Conversation** | Working memory for one agent and scope. |
| **AgentMessage** | A message within a conversation. |
| **Run** | A work episode. Status, outcome, diff, artifacts, accounting. |
| **Artifact** | A registered deliverable. Capped and deduplicated per run. |
| **Turn** | One dispatch, carrying a trace identifier. |
| **DispatchOutbox** | Persisted dispatch frames for at-least-once delivery. |
| **Workflow** | Column and gate definitions. |
| **GateEvaluation** | What was asked, what came back, allow or block, when. |

### Conversation scope

A conversation is keyed by agent and scope string:

- `task:<task_id>`
- `chat:project:<project_id>`
- `chat:default`

Scopes isolate memory. See [Core concepts](./concepts.md).

## Organisation scoping

Rows are stamped with an organisation on insert, and reads are scoped to the caller's organisation by session-level hooks rather than by each call site remembering to filter.

Cross-organisation access requires an explicit privileged escape, used for setup and administration.

## Database policy

Postgres in development, QA, production, and tests. The test harness starts an ephemeral Postgres container per session and gives each test a fresh schema.

Tests never use SQLite. Production is Postgres, so tests are too. Behaviour that differs between engines — dialect quirks, constraint timing, JSON handling — would otherwise pass in tests and fail in production.

## Migrations

Migrations live in `backend/db.py` and run at startup, applied idempotently.
