---
id: gates-and-evidence
title: Gates and evidence
sidebar_label: Gates and evidence
---

# Gates and evidence

The gate engine decides whether a task may change column. It reads facts from trusted sources rather than trusting an agent's account of itself.

For the user-facing view, see [Evidence gates](../user-guide/gates.md).

## The failure this replaced

Approval used to be a phrase. A reviewer agent wrote `REVIEW: APPROVE` in a comment, and the platform searched comments for those words.

Three failure modes followed:

1. Any agent could produce the words, including by quoting the rule.
2. A reviewer that rejected the work still ended its session successfully, and could merge the code by mentioning the phrase while explaining itself.
3. A refused merge left only a log line, with nothing for a person to open.

Approval is now a structured action. `submit_review` records a verdict field stamped with actor and timestamp. Comment text has no effect on approval, and a test pins that behaviour.

## Evidence providers

A provider answers one question from one source.

| Provider | Question | Source |
|---|---|---|
| `human_approval` | Did a reviewer approve? | The recorded verdict |
| `github_pr` | Did the pull request merge? | GitHub, via the platform's credentials |
| `ci` | Did checks pass? | GitHub checks, by name |
| `commit` | Does this commit exist? | GitHub |

### Two invariants

**The platform asks with its own credentials.** An agent is never the source of evidence about itself, so it cannot supply a doctored answer.

**Unknown blocks.** If a source is unreachable, credentials are absent, or a check has not run, the answer is `unknown`, and unknown is treated as "no". Silence is never approval.

:::note
`human_approval` is live. `github_pr`, `ci`, and `commit` are implemented and wired but need GitHub App credentials. Without them they answer `unknown` and therefore block. Failing closed is intentional.
:::

## Gate evaluation

On a transition:

1. The workflow definition supplies the gates for that transition.
2. Each gate asks its providers.
3. Any missing or negative answer blocks the move.
4. The evaluation is recorded with an evidence snapshot.
5. On failure the API returns 422 with `failed_gates` and plain-language reasons.

Typical checks:

| Transition | Evidence |
|---|---|
| Into `todo` | A definition of done exists |
| Into `review` | A branch or pull request exists |
| Into `done` | All definition-of-done items checked, pull request linked |

## The audit record

Every evaluation writes what was asked, what came back, whether it allowed or blocked, and when. The record is stored on the task and readable through the API.

This turns "the system refused" into a sentence with a record behind it.

## The standing rule

Any mechanism deciding task movement or approval must be:

1. Declared in workflow configuration
2. Evaluated through the gate and evidence engine
3. Recorded with an evidence snapshot
4. Visible in the interface

No hidden heuristics. No string-matching on comment text. No inferring intent from move history. A decision that cannot be seen cannot be steered or trusted, so it does not ship.

This constrains contributions. A feature that decides task movement by any other route will be rejected regardless of how well it works.

## Adding a provider

1. Implement the provider contract in `backend/forge/evidence.py`.
2. Return `unknown` for anything you cannot verify. Never guess.
3. Use platform credentials, never credentials supplied by the subject.
4. Test the unknown path explicitly. It is the one that matters.
