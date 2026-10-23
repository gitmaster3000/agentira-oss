# fix/openclaw-agent-model proof

$ .venv/bin/python -m pytest agentira-cli/tests/test_openclaw_ws_model.py -q
```
...                                                                      [100%]
3 passed in 0.04s
```

$ .venv/bin/python -m pytest agentira-cli/tests -q
```
=========================== short test summary info ============================
FAILED agentira-cli/tests/test_gateway_connect_contract.py::test_identity_still_valid_in_installed_openclaw
FAILED agentira-cli/tests/test_openclaw_pairing_contract.py::test_pairing_method_names_still_exported
FAILED agentira-cli/tests/test_openclaw_pairing_contract.py::test_agent_requires_operator_write
3 failed, 316 passed, 1 skipped in 24.25s
```

Red first: before the fix 2 of 3 new tests failed (no sessions.patch sent). Backend untouched; backend suite not run. Gateway method found in installed openclaw dist: ChatSendParamsSchema is closed with no model; SessionsPatchParamsSchema accepts model, needs operator.write for {key, model}.
