# Proof: feat/conductor-night-snapshot

## Snapshot tests
`python -m pytest backend/tests/test_work_snapshot.py -v`
```
backend/tests/test_work_snapshot.py::test_lists_done_review_and_runs_and_ignores_older PASSED [  4%]
backend/tests/test_work_snapshot.py::test_project_filter PASSED          [  9%]
backend/tests/test_work_snapshot.py::test_in_flight_listed PASSED        [ 13%]
backend/tests/test_work_snapshot.py::test_blockers_needs_input_and_answered_not_listed PASSED [ 18%]
backend/tests/test_work_snapshot.py::test_blocker_when_redispatch_attempts_spent PASSED [ 22%]
backend/tests/test_work_snapshot.py::test_offline_runtime_is_a_blocker_with_plain_message PASSED [ 27%]
backend/tests/test_work_snapshot.py::test_unbound_stale_runtime_ignored PASSED [ 31%]
backend/tests/test_work_snapshot.py::test_markdown_links_tasks PASSED    [ 36%]
backend/tests/test_work_snapshot.py::test_allowed_project_ids_limits_scope_and_hides_health PASSED [ 40%]
backend/tests/test_work_snapshot.py::test_config_exposes_interval_default_zero PASSED [ 45%]
backend/tests/test_work_snapshot.py::test_agent_dict_and_status_endpoint_expose_interval PASSED [ 50%]
backend/tests/test_work_snapshot.py::test_interval_zero_schedules_nothing PASSED [ 54%]
backend/tests/test_work_snapshot.py::test_interval_n_schedules_job PASSED [ 59%]
backend/tests/test_work_snapshot.py::test_quiet_window_posts_nothing PASSED [ 63%]
backend/tests/test_work_snapshot.py::test_blocker_posts_one_notification_per_admin_and_chat_message PASSED [ 68%]
backend/tests/test_work_snapshot.py::test_activity_without_blocker_posts PASSED [ 72%]
backend/tests/test_work_snapshot.py::test_job_noop_when_interval_zero PASSED [ 77%]
backend/tests/test_work_snapshot.py::test_mcp_tool_returns_markdown_and_dict PASSED [ 81%]
backend/tests/test_work_snapshot.py::test_two_orgs_each_admin_gets_only_own_snapshot PASSED [ 86%]
backend/tests/test_work_snapshot.py::test_quiet_org_gets_nothing_while_other_gets_one PASSED [ 90%]
backend/tests/test_work_snapshot.py::test_conductor_status_shows_only_callers_snapshot PASSED [ 95%]
backend/tests/test_work_snapshot.py::test_mcp_snapshot_limited_to_callers_org PASSED [100%]
=== 22 passed in 7.40s ===
```

## Full backend suite
`python -m pytest backend/tests/ -q -n 4` → `1112 passed in 68.63s`

## Multi-org isolation
The scheduled job runs once per org with that org pinned: snapshot, admin
notifications and Conductor chat note stay inside the org; last result is kept
per org and `GET /api/forge/conductor` returns only the caller's. Covered by
`test_two_orgs_each_admin_gets_only_own_snapshot`,
`test_quiet_org_gets_nothing_while_other_gets_one`,
`test_conductor_status_shows_only_callers_snapshot`,
`test_mcp_snapshot_limited_to_callers_org`.

## Frontend
`cd frontend && npx vitest run src/pages/forge/ConductorPage.summary.test.js && npx vite build`
```
 ✓ src/pages/forge/ConductorPage.summary.test.js (3 tests) 1ms
 Test Files  1 passed (1)
      Tests  3 passed (3)
✓ built in 2.38s
```

## Lint
`uvx ruff check <changed files> --output-format concise` → 3 F401 in `backend/forge/scheduler.py` (unused `datetime`, `timezone`, `ForgeRuntime` imports, pre-existing, left alone). New files clean.

## Not verified
No isolated live stack was started; the scheduler job, notification rows and
chat message are verified through the testcontainers Postgres tests only.
Web-push delivery (VAPID) not exercised.
