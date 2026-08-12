---
id: pull-requests
title: Pull requests
sidebar_label: Pull requests
---

# Pull requests

## Before you open one

```bash
git checkout -b fix/short-description

# write the failing test, watch it fail for the right reason, then make it pass

python -m pytest backend/tests/ -q      # needs Docker running
cd frontend && npx vite build           # if you touched the interface
cd docs-oss && npm run build            # if you touched documentation
```

## Opening it

Open against `main`.

Continuous integration must be green: unit tests, Compose configuration validation, and an integration smoke test that boots the backend and MCP.

Comment `/integration-test` on the pull request to run the full suite with the CLI installed.

## Writing the description

Say what changed, why, and how you verified it.

**"Tests pass" is not verification.** Name the test, or paste the command output. This is checked.

A useful description:

```markdown
## What
Adds a TTL to READY runs so a vanished daemon cannot hold a capacity slot forever.

## Why
AP-478. Four stale READY runs pinned implementer-1 at capacity, so the
Conductor read the agent as busy and never dispatched.

## How verified
- New test `test_runs.py::test_ready_run_expires_after_ttl` — fails before,
  passes after.
- Full suite: 758 passed.
- Manually: started a run, killed the daemon, confirmed the run expired and
  the slot freed.
```

## Scope

Keep changes surgical. Touch what the change needs and nothing adjacent.

If you spot unrelated dead code, mention it in the description rather than deleting it in the same diff.

A large diff containing one real change and a lot of incidental reformatting is hard to review and likely to be sent back.

## Review

Reviews come from maintainers and, increasingly, from the Reviewer agent.

Agent review comments are advisory. A human makes the merge call.

When you receive review feedback, verify it before acting on it. A reviewer — human or agent — can be wrong. If you think a comment is mistaken, say so with your reasoning rather than making a change you believe is incorrect.

## Documentation

A behaviour change without a documentation update is half-shipped. Update the affected page in `docs-oss/`, the relevant decision record, or the runbook in the same pull request.

`npm run build` in `docs-oss/` must pass. Broken links fail the build by design.

See the [documentation style guide](./documentation-style.md).

## What gets rejected

Beyond ordinary quality problems:

**Hidden decision logic.** Anything that decides task movement or approval outside the gate and evidence engine. No string-matching on comments, no inferring intent from move history. See [Gates and evidence](../technical/gates-and-evidence.md).

**Engineer-only user-facing text.** Interface strings that assume Git or infrastructure knowledge, with no plain-language default.

**Inline database calls in services.** Reads and writes go through repository functions.

**Hardcoded prompt text.** Prompts are configuration. See [Code conventions](./code-conventions.md).

**Tests that build their own database.** Use the shared fixtures.

**Weakened assertions.** Fix the code instead.
