# Proof: feat/a2a-agent-messaging

Environment: worktree `/Users/alifaraz/Projects/agentira-wt/a2a`, `.venv` from `uv venv .venv && uv pip install -r requirements-dev.lock && uv pip install -e .`, Postgres via testcontainers (Docker). The running Agentira stack, the main checkout, the daemon and OpenClaw were not touched.

## 1. New A2A tests

```
$ python -m pytest backend/tests/test_a2a.py -v -p no:warnings
test_a2a.py::test_ask_stores_thread_message_and_wakes_target PASSED
test_a2a.py::test_ask_with_task_mirrors_line_on_task_feed_and_names_task PASSED
test_a2a.py::test_ask_records_asker_live_run_as_origin PASSED
test_a2a.py::test_reply_routes_to_asker_wake_when_no_live_run PASSED
test_a2a.py::test_reply_lands_in_askers_live_run_conversation PASSED
test_a2a.py::test_reply_after_asker_run_finished_wakes_a2a_scope PASSED
test_a2a.py::test_non_participant_cannot_post_to_thread PASSED
test_a2a.py::test_self_message_rejected PASSED
test_a2a.py::test_unknown_agent_rejected PASSED
test_a2a.py::test_cross_org_rejected PASSED
test_a2a.py::test_archived_agent_rejected PASSED
test_a2a.py::test_rate_limit_30_per_thread_per_hour PASSED
test_a2a.py::test_rate_limit_ignores_messages_older_than_an_hour PASSED
test_a2a.py::test_body_capped PASSED
test_a2a.py::test_empty_body_rejected PASSED
test_a2a.py::test_not_an_agent_cannot_ask PASSED
test_a2a.py::test_undeliverable_target_still_stores_message PASSED
test_a2a.py::test_a2a_message_to_busy_agent_is_queued_then_flushed PASSED
test_a2a.py::test_get_agent_thread_orders_messages PASSED
test_a2a.py::test_get_agent_thread_unknown_or_foreign PASSED
test_a2a.py::test_hand_off_reassigns_comments_and_dispatches PASSED
test_a2a.py::test_hand_off_to_self_rejected PASSED
test_a2a.py::test_hand_off_dispatch_error_reported PASSED
test_a2a.py::test_hand_off_needs_project_access PASSED
test_a2a.py::test_list_agents_returns_cards_for_callers_org_only PASSED
test_a2a.py::test_list_agents_filters_by_project PASSED
test_a2a.py::test_list_agents_hides_archived PASSED
============================== 27 passed in 7.22s ==============================
```

## 2. Full backend suite

```
$ python -m pytest backend/tests/ -q -n 4
1117 passed, 83 warnings in 70.66s (0:01:10)
```

## 3. Lint on the new/changed modules

```
$ ruff check backend/forge/a2a.py backend/forge/repos/a2a.py backend/tests/test_a2a.py backend/forge/msg_queue.py
All checks passed!
```

(`ruff check backend/` as a whole reports 127 findings that were already there; none are in these files.)

## 4. Startup migration on a fresh Postgres

`init_db()` runs `create_all` then `run_migrations()`. The two new tables are in `_ORG_SCOPED_TABLES`, so they get org row-level security. Checked on a throwaway testcontainers Postgres (create_all, then run_migrations twice to prove it is idempotent):

```
forge_a2a_threads rls (True, True) policies ['org_iso']
forge_a2a_messages rls (True, True) policies ['org_iso']
```

## Not done

- No browser/UI work and no live end-to-end run against a real daemon: delivery is verified by capturing `send_runtime_message` and, for the busy-target case, by the real `msg_queue` on Postgres.
