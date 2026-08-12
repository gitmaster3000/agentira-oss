---
id: conductor
title: The Conductor
sidebar_label: The Conductor
---

# The Conductor

The Conductor is the built-in orchestrator. It plans projects, breaks work down, and can dispatch tasks without you clicking Run.

It joins every new project automatically.

## What it does on demand

When you run the **Plan this project** task, the Conductor:

1. Reads the project description and attachments.
2. Chooses a technology stack and justifies each choice.
3. Writes a one-page plan and registers it as an artifact.
4. Creates 3–8 child tasks, each with a description and a definition of done.
5. Declares an outcome.

You can run this again later. Comment on the task with what changed, and it replans.

## Autonomous mode

Turn autonomy on and the Conductor works on a schedule instead of waiting for you.

Enable it in the Conductor's own settings. Three cadences are configurable:

| Cycle | What it does |
|---|---|
| **Queue tick** | Looks for work ready to dispatch and dispatches it |
| **Planning turn** | Reviews the backlog and promotes tasks into `todo` with verification-shaped definitions of done |
| **Daily report** | Summarises what happened and what is stuck |

Each interval is set on the Conductor's profile. There is no global switch buried elsewhere.

## What autonomy changes

With autonomy on, tasks move without you initiating them. Agentira compensates by making every decision inspectable:

- Each planning cycle is recorded as its own turn with its own scope.
- Each dispatch appears on the board and in the activity log.
- Every transition still passes its gates. Autonomy does not bypass evidence.

Planning turns are isolated per project. One project's planning context never leaks into another.

## Guidance for autonomy

Autonomy amplifies whatever your backlog already says. Before enabling it:

**Write verifiable definitions of done.** The Conductor promotes tasks based on what they claim to require. Vague criteria produce vague work.

**Enable gates first.** Gates are what stop an autonomous loop from marking its own work complete. See [Evidence gates](./gates.md).

**Set priorities honestly.** The Conductor uses priority to choose what to dispatch. If everything is critical, ordering is arbitrary.

**Start with one project.** Watch a full cycle before widening.

## Injection safety

The Conductor reads text that people and agents wrote — task titles, descriptions, comments. That text is untrusted input, not instruction.

Every planning turn applies an injection guard, and webhook payloads carry structured fields rather than a pre-composed message, so user content is never passed raw into a prompt.

## Monitoring

Watch three things:

| Signal | Where |
|---|---|
| Planning turn errors | Conductor run history |
| Failed runs | Run list, filtered by outcome |
| Daemon connection | `agentira daemon status` |

An autonomous loop that cannot dispatch looks identical to an idle one. If nothing has moved for a while, check the daemon before assuming the backlog is empty.
