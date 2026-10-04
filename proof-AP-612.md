# proof-AP-612 — interrupted runs resume instead of failing

**Limitation (honest):** not a live daemon-kill in an isolated stack. Proof is the
reconciler against a real Postgres (testcontainers) with the daemon's re-dispatch
stubbed at `dispatch_pending_run`. The live kill/launchd end-to-end was NOT run.

```
$ ~/.cache/agentira-verify/venv/bin/python -m pytest backend/tests/test_stale_run_reconciler.py backend/tests/test_usage_limits.py -q
31 passed
```
New tests: stale run with session → resumed (PENDING, restart_resumes=1, dispatched with resume=True);
no session → still FAILED; budget spent (FORGE_RESTART_MAX_RESUMES=2, resumes=2) → FAILED + admin notification.
