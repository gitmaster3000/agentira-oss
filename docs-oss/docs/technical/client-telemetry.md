# Browser telemetry

Agentira records what each user actually experiences in the browser, so a complaint like "typing was slow" or "clicking did nothing" can be answered from data instead of by re-testing.

## What is collected

| Kind | When | Log level |
|---|---|---|
| `error` | Uncaught error, unhandled promise rejection, React render crash (the user sees a "Something went wrong" screen with an error id) | ERROR |
| `interaction` | A keystroke or click took long to paint (one line per interaction, with the element, e.g. `textarea[Add a comment…]`) | WARNING |
| `longtask` | The page froze (main thread busy); count and longest per flush | WARNING |
| `api` | An API call failed, or was slow as the browser saw it (server time + network) | INFO (DEBUG at debug level) |
| `api_summary` | Count / average / max per endpoint for the other calls | INFO |
| `page_load` | Time to first byte, DOM ready, load, largest paint, bytes transferred | INFO |
| `debug_on` | Debug level was switched on for a user (by whom, why) | WARNING |

Every line also carries: user, org, route (ids collapsed to `:id`), release (deployed commit), session id, browser, time zone, network type, screen, CPU cores, memory, and `self_ms` — the CPU time telemetry itself has used in that tab.

Never collected: field values, request or response bodies, tokens.

## Levels

| Level | Who | Thresholds | Sends |
|---|---|---|---|
| `info` | everyone, always | interactions and freezes ≥ 200 ms, API calls ≥ 1.5 s or failed | at most once a minute, in idle time |
| `debug` | one user, for a limited time | interactions and freezes ≥ 50 ms, every API call | every 10 s |

Debug is switched on:

- **by an admin**, for a user who complains:
  ```bash
  curl -X POST https://<host>/api/client-logs/debug \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"user": "babar", "minutes": 60, "reason": "typing lag"}'
  curl https://<host>/api/client-logs/debug -H "Authorization: Bearer $TOKEN"            # active
  curl -X DELETE https://<host>/api/client-logs/debug/babar -H "Authorization: Bearer $TOKEN"
  ```
- **automatically**, for 30 minutes, when a user's info-level data shows a crash or an interaction ≥ 1 s. Set `AGENTIRA_TELEMETRY_AUTO_MINUTES` on the backend to change the duration (`0` turns this off).

The browser learns its level from the reply to its own log upload and once at page load — no extra polling. A change takes effect on the user's next upload (within 5 minutes) or page load.

## Reading it

Everything is one JSON line per event in the backend log, prefixed `CLIENT`:

```bash
railway logs -s backend --since 1d --filter "CLIENT"                      # all
railway logs -s backend --since 1d --filter "CLIENT AND @level:error"     # crashes
railway logs -s backend --since 1d --filter "CLIENT AND interaction"      # slow typing/clicks
railway logs -s backend --since 1d --filter "CLIENT AND babar"            # one user
```

Locally: `docker compose logs backend | grep CLIENT`.

## Overhead

Per API call: a few additions. Observers only act on entries that are already slow. Uploads are small, batched, sent in idle time with `keepalive`. `self_ms` on every line shows the real cost; in testing it stayed at 0–1 ms per tab.

## Code

- Browser: `frontend/src/telemetry.js`, `frontend/src/components/ErrorBoundary.jsx`, API timing in `frontend/src/api.js`
- Backend: `backend/client_telemetry.py` (intake, levels, admin commands), `backend/repos/client_debug.py`, table `client_debug_sessions`
