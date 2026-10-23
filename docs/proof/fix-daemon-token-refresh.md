# Proof: fix/daemon-token-refresh

Run 2026-10-23T23:06Z in the worktree; no real daemon/stack touched (tests use testcontainers Postgres).

## New backend tests
```
$ python -m pytest backend/tests/test_daemon_refresh.py backend/tests/test_runtime_offline_reason.py -v -q -p no:warnings
test_daemon_refresh.py::test_login_issues_refresh_token_and_stores_only_a_hash PASSED [  6%]
test_daemon_refresh.py::test_login_without_device_info_still_works PASSED [ 12%]
test_daemon_refresh.py::test_exchange_returns_fresh_access_token_and_rotated_refresh_token PASSED [ 18%]
test_daemon_refresh.py::test_exchange_slides_expiry_and_stamps_last_used PASSED [ 25%]
test_daemon_refresh.py::test_old_refresh_token_is_dead_after_use PASSED [ 31%]
test_daemon_refresh.py::test_reuse_of_an_old_token_revokes_the_whole_chain PASSED [ 37%]
test_daemon_refresh.py::test_reuse_does_not_touch_other_devices PASSED [ 43%]
test_daemon_refresh.py::test_expired_refresh_token_is_rejected PASSED [ 50%]
test_daemon_refresh.py::test_revoked_refresh_token_is_rejected PASSED [ 56%]
test_daemon_refresh.py::test_revoke_kills_the_rotated_chain_too PASSED [ 62%]
test_daemon_refresh.py::test_unknown_or_missing_token_is_rejected PASSED [ 68%]
test_daemon_refresh.py::test_profile_no_longer_admin_cannot_refresh PASSED [ 75%]
test_daemon_refresh.py::test_archived_profile_cannot_refresh PASSED [ 81%]
test_runtime_offline_reason.py::test_silent_for_over_five_minutes_explains_signed_out PASSED [ 87%]
test_runtime_offline_reason.py::test_recently_seen_offline_runtime_is_just_reconnecting PASSED [ 93%]
test_runtime_offline_reason.py::test_online_runtime_has_no_reason PASSED [100%]
============================== 16 passed in 4.15s ==============================
```

## New CLI tests
```
$ python -m pytest agentira-cli/tests/test_daemon_auth.py -v -p no:warnings
test_daemon_auth.py::test_refreshes_when_less_than_24h_left_and_persists_rotated_tokens PASSED [  4%]
test_daemon_auth.py::test_no_refresh_when_plenty_of_time_left PASSED [  9%]
test_daemon_auth.py::test_static_keys_are_never_refreshed PASSED [ 14%]
test_daemon_auth.py::test_expired_token_is_refreshed_too PASSED [ 19%]
test_daemon_auth.py::test_from_credentials_only_for_the_login_token PASSED [ 23%]
test_daemon_auth.py::test_401_refreshes_and_retries_exactly_once PASSED [ 28%]
test_daemon_auth.py::test_still_401_after_refresh_raises_without_looping PASSED [ 33%]
test_daemon_auth.py::test_non_401_errors_do_not_trigger_refresh PASSED [ 38%]
test_daemon_auth.py::test_client_without_auth_behaves_as_before PASSED [ 42%]
test_daemon_auth.py::test_second_thread_reuses_the_token_the_first_already_renewed PASSED [ 47%]
test_daemon_auth.py::test_failed_refresh_logs_one_error_per_ten_minutes PASSED [ 52%]
test_daemon_auth.py::test_failed_refresh_backs_off_but_keeps_retrying PASSED [ 57%]
test_daemon_auth.py::test_recovers_when_the_server_comes_back PASSED [ 61%]
test_daemon_auth.py::test_server_down_is_reported_differently_from_signed_out PASSED [ 66%]
test_daemon_auth.py::test_legacy_login_without_refresh_token_says_signed_out PASSED [ 71%]
test_daemon_auth.py::test_running_daemon_picks_up_a_fresh_daemon_login PASSED [ 76%]
test_daemon_auth.py::test_failed_save_does_not_regress_to_the_old_file_token PASSED [ 80%]
test_daemon_auth.py::test_heartbeat_renews_proactively_first PASSED [ 85%]
test_daemon_auth.py::test_ws_auth_rejection_triggers_refresh_before_reconnect PASSED [ 90%]
test_daemon_auth.py::test_login_saves_refresh_token_with_0600 PASSED [ 95%]
test_daemon_auth.py::test_login_against_an_older_backend_still_works PASSED [100%]
============================== 21 passed in 0.20s ==============================
```

## Full CLI suite
```
$ python -m pytest agentira-cli/tests -q -p no:warnings
agentira-cli/tests/test_openclaw_pairing_contract.py:50: FileNotFoundError
=========================== short test summary info ============================
FAILED agentira-cli/tests/test_gateway_connect_contract.py::test_identity_still_valid_in_installed_openclaw
FAILED agentira-cli/tests/test_openclaw_pairing_contract.py::test_pairing_method_names_still_exported
FAILED agentira-cli/tests/test_openclaw_pairing_contract.py::test_agent_requires_operator_write
3 failed, 334 passed, 1 skipped in 28.14s
```
The 3 failures read the installed OpenClaw under the real ~/.openclaw (`FileNotFoundError ... plugin-runtime-deps/openclaw-2026.4.25.../dist/method-scopes-*.js`); environmental, unrelated to this change (read-only access, nothing modified).

## Full backend suite
```
$ python -m pytest backend/tests/ -q -n 4
..........................                                               [100%]
1106 passed in 64.07s (0:01:04)
```
