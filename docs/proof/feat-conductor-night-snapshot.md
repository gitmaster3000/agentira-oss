# Proof: feat/conductor-night-snapshot

## Snapshot tests
`python -m pytest backend/tests/test_work_snapshot.py -v`
```
backend/tests/test_work_snapshot.py::test_lists_done_review_and_runs_and_ignores_older PASSED [  5%]
backend/tests/test_work_snapshot.py::test_project_filter PASSED          [ 11%]
backend/tests/test_work_snapshot.py::test_in_flight_listed PASSED        [ 16%]
backend/tests/test_work_snapshot.py::test_blockers_needs_input_and_answered_not_listed PASSED [ 22%]
backend/tests/test_work_snapshot.py::test_blocker_when_redispatch_attempts_spent PASSED [ 27%]
backend/tests/test_work_snapshot.py::test_offline_runtime_is_a_blocker_with_plain_message PASSED [ 33%]
backend/tests/test_work_snapshot.py::test_unbound_stale_runtime_ignored PASSED [ 38%]
backend/tests/test_work_snapshot.py::test_markdown_links_tasks PASSED    [ 44%]
backend/tests/test_work_snapshot.py::test_allowed_project_ids_limits_scope_and_hides_health PASSED [ 50%]
backend/tests/test_work_snapshot.py::test_config_exposes_interval_default_zero PASSED [ 55%]
backend/tests/test_work_snapshot.py::test_agent_dict_and_status_endpoint_expose_interval PASSED [ 61%]
backend/tests/test_work_snapshot.py::test_interval_zero_schedules_nothing PASSED [ 66%]
backend/tests/test_work_snapshot.py::test_interval_n_schedules_job PASSED [ 72%]
backend/tests/test_work_snapshot.py::test_quiet_window_posts_nothing PASSED [ 77%]
backend/tests/test_work_snapshot.py::test_blocker_posts_one_notification_per_admin_and_chat_message PASSED [ 83%]
backend/tests/test_work_snapshot.py::test_activity_without_blocker_posts PASSED [ 88%]
backend/tests/test_work_snapshot.py::test_job_noop_when_interval_zero PASSED [ 94%]
backend/tests/test_work_snapshot.py::test_mcp_tool_returns_markdown_and_dict PASSED [100%]
============================== 18 passed in 6.04s ==============================
```

## Full backend suite
`python -m pytest backend/tests/ -q -n 4` → `1108 passed in 60.22s`

## Frontend
`cd frontend && npx vitest run src/pages/forge/ConductorPage.summary.test.js && npx vite build`
```
 ✓ src/pages/forge/ConductorPage.summary.test.js (3 tests) 1ms
 Test Files  1 passed (1)
      Tests  3 passed (3)
✓ built in 2.38s
```

## Lint
`uvx ruff check <changed files>`
```
    |
note: This is an unsafe fix and may change runtime behavior

Found 4 errors.
[*] 3 fixable with `--fix` (1 unsafe fix available with `--fix --unsafe-fixes`).
```

## Not verified
No isolated live stack was started; the scheduler job, notification rows and
chat message are verified through the testcontainers Postgres tests only.
Web-push delivery (VAPID) not exercised.
