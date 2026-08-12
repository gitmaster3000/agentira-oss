---
id: index
title: Contributing
sidebar_label: Overview
slug: /contributing/
---

# Contributing

Agentira runs its own development on Agentira. The backlog you would work from is a live Agentira board, worked by the same mix of people and agents the product is for.

That is unusual, so this guide focuses on what differs from a normal repository.

## Where work lives

**GitHub Issues** — bug reports, feature ideas, questions. Anyone with a GitHub account. Start here.

**The Agentira board** — the canonical backlog, sprints, and assignment. It lives on a hosted Agentira instance rather than in GitHub Projects. To take real work rather than drive-by fixes, open an issue asking for access and a maintainer will create an account for you.

You do not need board access to send a pull request. You need it to be assigned something.

## Getting started

| Step | Guide |
|---|---|
| 1. Get the stack running | [Development setup](./development-setup.md) |
| 2. Learn the code rules | [Code conventions](./code-conventions.md) |
| 3. Learn the test rules | [Testing](./testing.md) |
| 4. Open a pull request | [Pull requests](./pull-requests.md) |
| 5. Write documentation | [Documentation style](./documentation-style.md) |

Getting the stack running from a clean clone is itself a test. If it does not work for you, that is a bug worth reporting on its own — the cold-start path is the one we most want to keep honest.

## Two rules that override preference

These are not style opinions. A change that breaks either will be rejected however well it works.

### Autonomy is transparent or it is not shipped

Any mechanism that decides task movement or approval must be:

1. Declared in workflow configuration
2. Evaluated through the gate and evidence engine
3. Recorded with an evidence snapshot
4. Visible in the interface

No hidden heuristics. No string-matching on comment text. No inferring intent from move history. If a decision cannot be seen in the interface or the audit trail, it cannot be steered or trusted.

This is the product, not a nice-to-have. See [Gates and evidence](../technical/gates-and-evidence.md).

### Plain language is a product rule

Agentira's audience is founders, small software teams, and solo builders — not Git or infrastructure experts.

Anything user-facing stays in plain language by default: interface labels, settings, run badges, warnings, error text. Technical internals — branch names, base points, Git mechanics, daemon details — go behind an optional **Advanced** reveal.

A non-engineer must see the same honest status an engineer does, in words they understand. This applies to every feature, every time.

## Security

Do not open a public issue for a vulnerability. Email the maintainer address on the GitHub profile of this repository's owner, with a description and reproduction steps.

Two standing cautions, since Agentira runs code on contributors' machines:

**Sandbox enforcement is incomplete.** Modes are configured and logged but not enforced per runtime. An agent can reach what your user account can reach.

**Never commit a real credential**, including in test fixtures. The convention is obvious fakes: `bob@x.io`, `@agentira.local`, `acme.dev`.

## Licence

By contributing you agree your contributions are licensed under [Apache-2.0](https://github.com/gitmaster3000/agentira-oss/blob/main/LICENSE), the same licence as the project.
