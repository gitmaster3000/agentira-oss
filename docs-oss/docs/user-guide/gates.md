---
id: gates
title: Evidence gates
sidebar_label: Evidence gates
---

# Evidence gates

A gate is a check that runs when a task tries to change column. It asks for facts from trusted sources instead of trusting what an agent says about itself.

Gates are opt-in per project. Enable them in **Project Settings → Gates**.

## Why gates exist

Before gates, a reviewer agent approved work by writing a message:

```
REVIEW: APPROVE — looks good to me
```

The platform searched comments for that phrase. That is a weak lock, and it broke in three ways:

1. **Anyone could type it.** The words are just text. An implementer, a confused agent, or a quoted line in a summary could produce them.
2. **A rejection could pass.** A reviewer that rejected work still ended its session successfully. If it mentioned the phrase while explaining the rules, the code merged anyway.
3. **Nobody could see why.** A refused merge left only a log line. There was nothing for a person to open.

Approval is now a structured action, not a phrase. The reviewer calls a tool that records a verdict field stamped with who decided and when. Typing `REVIEW: APPROVE` in a comment now does nothing at all, and a test proves it.

## Evidence providers

A gate asks providers for facts. Each provider answers one question from one trusted source.

| Provider | Question | Source |
|---|---|---|
| `human_approval` | Did a reviewer actually approve this? | The recorded verdict |
| `github_pr` | Did the pull request really merge? | GitHub, via the platform's own credentials |
| `ci` | Did the tests and build actually pass? | GitHub checks, by name |
| `commit` | Does this commit really exist? | GitHub |

Two rules make this trustworthy.

**The platform asks with its own credentials, never the agent's.** An agent cannot hand over a doctored answer, because it is never asked. The platform queries the source directly.

**"I do not know" always blocks.** If the source is unreachable, credentials are missing, or the check has not run yet, the answer is `unknown`. Unknown is treated exactly like "no". Silence is never approval.

:::note Current status
`human_approval` is live. `github_pr`, `ci`, and `commit` are built and connected, but require GitHub App credentials that are not wired up by default. Until you configure them, those three answer `unknown` and therefore block. That is the safe direction to fail in.
:::

## What gates check

Typical column-exit checks:

| Transition | Required evidence |
|---|---|
| Into `todo` | The task has a definition of done |
| Into `review` | A branch or pull request exists |
| Into `done` | Every definition-of-done item is checked, and a pull request is linked |

When a move fails, the interface names which gates failed and why. The API returns a structured error listing them.

## The audit record

Every evaluation writes a record: what was asked, what came back, whether it allowed or blocked, and when. The record is stored on the task and readable through the API.

So instead of "something decided something somewhere", you get a sentence and the record behind it:

> Merge refused — no verified reviewer approval was found for this task since the run started.

## The standing rule

Any mechanism that decides task movement or approval must be:

1. Declared in workflow configuration
2. Evaluated through the gate and evidence engine
3. Recorded with an evidence snapshot
4. Visible in the interface

No hidden heuristics. No string-matching on comment text. No inferring intent from move history. If a decision cannot be seen in the interface or the audit trail, it cannot be steered or trusted, so it does not ship.

## Workflow templates

Projects can adopt a YAML workflow template that defines columns and their gates. A production-readiness template ships with Agentira as a starting point.
