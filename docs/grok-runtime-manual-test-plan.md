# Grok runtime manual test plan

1. Confirm the installed CLI advertises `--single` and `streaming-json`:
   `grok --help`.
2. From a disposable project checkout, run a trivial headless turn:
   `grok --single 'Reply with exactly OK' --output-format streaming-json`.
3. Confirm the Agentira daemon detects Grok and reports a version:
   `agentira runtime list`.
4. Dispatch a trivial Grok agent run and confirm live text events appear,
   the run completes successfully, and no `unexpected argument` error is
   shown in the run diagnostics.

Manual verification performed on 2026-07-23:

- `grok --help` reported `--single` and output format `streaming-json`.
- The trivial headless command returned a streaming JSON response.
- The adapter integration test passed with a Grok-shaped executable that
  rejects `--verbose` and `stream-json`.
