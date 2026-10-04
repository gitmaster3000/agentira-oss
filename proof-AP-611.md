# Proof — usage limits pause runs and resume at reset

Fake runtime (hub seam) on ephemeral Postgres; real dispatch, complete_trigger, pause, runtime gate, scheduler sweep, resume.

```
$ pytest backend/tests/test_usage_limits_e2e.py -q -s
1. dispatched to fake runtime      run=running   reason=None resume_at=None runtime_limited_until=None
2. runtime reports limit error     run=paused    reason=usage_limit resume_at=2026-10-04T04:21:00+00:00 runtime_limited_until=2026-10-04T04:21:00+00:00
3. new dispatch to resting runtime -> 'Resting until 04:21 UTC — usage limit'
4. sweep one minute before reset   run=paused    reason=usage_limit resume_at=2026-10-04T04:21:00+00:00 runtime_limited_until=2026-10-04T04:21:00+00:00
5. sweep after reset -> resumed    run=running   reason=None resume_at=None runtime_limited_until=2026-10-04T04:21:00+00:00
6. runtime finishes the turn       run=completed reason=None resume_at=None runtime_limited_until=2026-10-04T04:21:00+00:00
resume frame session handle: 'claude-session-42'
1 passed, 4 warnings in 2.12s

$ pytest backend/tests/test_usage_limits.py -q
18 passed, 1 warning in 2.97s

$ pytest backend/tests -k "run or conductor or dispatch or state or agent or reconcil or scheduler or mcp"
372 passed, 544 deselected, 26 warnings in 68.25s (0:01:08)
```

Notes: step 5 shows the SAME run id resumed with session handle `claude-session-42`. Classification runs in the backend on the daemon-reported error text (no daemon release needed).
