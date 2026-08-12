---
id: code-conventions
title: Code conventions
sidebar_label: Code conventions
---

# Code conventions

These rules are enforced in review. They exist because each one was learned from a failure.

## Think before writing

Read the surrounding module. Name the contract you are targeting. List your assumptions. Do not start typing until the shape is clear.

## Surgical changes

Touch only what the change needs. Do not refactor adjacent code, reformat, or improve comments you happened to read.

If you spot unrelated dead code, say so in the pull request. Do not delete it in the same diff.

Every changed line should trace to the stated purpose of the change.

## Modular boundaries

**New domains get their own module.** `backend/<domain>.py`, or `backend/forge/<domain>.py`. Do not append another function to `services.py`.

**Functions by default.** Reach for a class only when polymorphism or genuine state makes it earn its place.

**Real foreign keys between modules.** No string references standing in for relationships.

`backend/forge/` is self-contained. Keep it that way.

Adding a whole new domain? Read `docs/adding-a-feature.md` in the repository first. It walks the gateway, handler, repository, and adapter layering end to end.

## No direct database calls in services

Orchestration modules must not call the session inline — no `db.query`, `db.add`, or `db.commit` in `services.py`, `forge/services.py`, `forge/conductor.py`, or any other orchestration module.

Every read and write goes through a per-domain repository function. **Services compose; repositories own the SQL.**

Inline queries leak ORM internals into business logic, hide N+1 traps, make the layer untestable without a real database, and break quietly when the schema moves.

Existing direct-database code is legacy. New code uses repositories. When you touch legacy code, migrate the queries you touched — not the whole file.

Repository functions either take a session or open their own. Pick one shape per module and stay consistent.

## Prompts are configuration, not code

Agent system prompts live on the profile row, edited in agent settings. Task content lives on the task row, edited in the task interface.

Three consequences:

1. No prompt text hardcoded in dispatch code.
2. Never re-apply a code constant over a user-edited row.
3. Seeding sets a field only when it is empty. This is the only acceptable shape.

A user's edit is authoritative. An upgrade must not overwrite it.

## Role and permission shape

A profile carries a stored `account_type` (`human`, `agentira_agent`, `external_agent`) **and** a many-to-many roles relationship (`admin`, `member`, `viewer`).

Build with `roles=[role_obj]`, never `role_id=`.

There is no bot role. Agents hold ordinary roles and pass the same permission checks people do.

## Maintain documentation as you change code

When you change behaviour, update the affected page in `docs-oss/`, the relevant decision record, or the runbook — in the same pull request.

A behaviour change without a documentation update is half-shipped. This is a review criterion.

Follow the [documentation style guide](./documentation-style.md).

## Commit messages

Conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `ci:`, `test:`.

Reference the board key when there is one:

```
fix(daemon): AP-412 enforce hermetic execution in container mode
```

## Naming and test data

Never commit a real credential, including in fixtures. Use obvious fakes: `bob@x.io`, `@agentira.local`, `acme.dev`.

## The two overriding rules

[Autonomy must be transparent](./index.md#autonomy-is-transparent-or-it-is-not-shipped) and [user-facing text stays in plain language](./index.md#plain-language-is-a-product-rule). Both override style preference and both are grounds for rejection.
