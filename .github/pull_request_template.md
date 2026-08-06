## What changed

<!-- One paragraph. What behavior is different after this PR. -->

## Why

<!-- The problem. Link the issue or board key (AP-###) if there is one. -->

## How it was verified

<!--
Name the test or paste the command output. "Tests pass" on its own is not
verification — reviewers check this.
-->

```
```

## Checklist

- [ ] A test covers the new behavior (or pins the behavior preserved)
- [ ] `python -m pytest backend/tests/ -q` passes locally
- [ ] `cd frontend && npx vite build` passes (if the UI changed)
- [ ] Docs updated in the same PR (`docs/`, an ADR, or a runbook) if behavior changed
- [ ] No credentials, real emails, or absolute home paths in the diff
- [ ] User-facing text is plain language; technical detail is behind an Advanced reveal
