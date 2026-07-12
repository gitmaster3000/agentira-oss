# Daemon Operations Runbook

How to diagnose, restart, and supervise the AgentIRA daemon.

## Quick reference

```bash
agentira daemon status          # Process + WS state + dry_run flag
agentira daemon logs -f         # Tail the daemon log
agentira daemon update          # Upgrade CLI from your instance's published wheel
agentira daemon restart         # Stop + start (backgrounds the new daemon)
agentira daemon stop            # Graceful SIGTERM
agentira daemon start           # Start in foreground (logs to stdout)
agentira daemon start --background  # Detach to background
```

## Install + upgrade (customers)

Install (first time):

```bash
curl -fsSL https://YOUR-INSTANCE/api/public/install.sh | bash
```

Upgrade (after operator redeploys backend with a newer CLI):

```bash
agentira daemon update
agentira daemon restart
```

The CLI asks `AGENTIRA_DAEMON_API_URL` (from `~/.agentira/.env`) for
`GET /api/public/cli-release`, then `pip install`s the wheel URL returned.
No GitHub token or private-repo access required.

> **Maintainers:** to *publish* a new daemon version (bump → build → bake →
> deploy) see [`daemon_release.md`](daemon_release.md). `daemon update` only
> sees a change after the backend is redeployed with a bumped version.

## Common failure modes

### 1. Daemon process is running but WS disconnected

**Symptoms:** `agentira daemon status` shows "running" but "WebSocket: DISCONNECTED". Triggers dispatched from the UI show "no daemon online" errors.

**Diagnosis:**
```bash
agentira daemon status --output json  # Check ws_connected field
agentira daemon logs -n 100           # Look for WS reconnect attempts
```

**Fix:** The daemon's WS reconnect loop should recover automatically (backoff: 1s → 2s → 5s → 10s → 30s → 60s). If it doesn't:
```bash
agentira daemon restart
```

**Root cause:** Usually the backend restarted or the network dropped. The reconnect loop handles this, but if the daemon process wedged before the loop could fire, restart is the fix.

### 2. Daemon comes back in dry_run mode

**Symptoms:** `agentira daemon status` shows "Mode: DRY-RUN". Triggers are received (visible in logs) but no subprocess spawns.

**Diagnosis:**
```bash
agentira daemon status   # Shows DRY-RUN warning
```

**Fix:**
```bash
agentira daemon restart  # Restart clears dry_run unless --dry-run is passed
```

The restart command explicitly resets `dry_run=False` unless you pass `--dry-run`.

### 3. Stale PID file

**Symptoms:** `agentira daemon status` shows "stopped (stale pid file points at dead PID X)".

**Diagnosis:** The daemon crashed or was killed without cleanup.

**Fix:**
```bash
agentira daemon start    # Overwrites the stale PID file
```

### 4. Trigger received but subprocess never spawns

**Symptoms:** Log shows "WS trigger received: trace=... kind=..." but no "Dispatched" follow-up.

**Diagnosis:** One of the pre-dispatch steps (materialize, MCP config write, worktree provision) timed out or errored.

**Fix:** Check the log for timeout errors immediately after the trigger line:
```bash
agentira daemon logs -n 200 | grep -A5 "trigger received"
```

Each step has a timeout (materialize: 30s, memory dirs: 10s, worktree: 60s). If a timeout fires, the run is marked failed with an actionable error message visible in the UI's run timeline.

### 5. Backend unreachable from daemon

**Symptoms:** WS never connects. Log shows repeated connection errors.

**Diagnosis:**
```bash
curl http://127.0.0.1:8111/api/health   # Is the backend up?
agentira daemon logs | grep "connect"    # What errors?
```

**Fix:** Ensure the backend is running. Check `AGENTIRA_DAEMON_API_URL` env var or `~/.agentira/config.yaml` `api_url` field.

## Architecture

```
Daemon process (local)
  ├── WS client → backend /api/forge/daemon/ws
  │     Reconnect loop: never stops, backoff [1,2,5,10,30,60]s
  │     On connect: sends {daemon_id, runtime_ids}
  │     Receives: trigger, cancel, pause, resume frames
  ├── Trigger handler
  │     1. materialize (30s timeout)
  │     2. ensure_memory_dirs (10s timeout)
  │     3. worktree provision (60s timeout)
  │     4. subprocess spawn (claude/openclaw)
  │     On any timeout → mark_dispatch_dropped → run fails visibly
  └── PID file + log file in ~/.agentira/
```

### WS keepalive + dispatch redelivery (AP-361 follow-up)

A redeploy or idle proxy hop can leave the daemon's WS half-open: the TCP
socket looks alive to both sides but frames stop flowing. Neither side's
`recv()` raises on its own, so without an active probe the server would keep
a dead connection registered forever, and every dispatch to it would vanish
silently — this is what happened in the AP-361 incident (daemon alive,
dispatch dropped, run failed with "Daemon offline at dispatch").

Both sides now probe with an app-level `{"type": "ping"}` / `{"type":
"pong"}` frame in addition to the WS library's own ping/pong:

- **Daemon** (`agentira_cli/daemon/ws_client.py`): sends a ping whenever its
  30s `recv` times out, and replies to server pings with a pong.
- **Server** (`backend/forge/ws_dispatch.py::handle_daemon_ws`): waits up to
  `FORGE_WS_HEARTBEAT_INTERVAL_S` (default 20s) for any frame; on timeout,
  sends a ping. If `FORGE_WS_HEARTBEAT_TIMEOUT_S` (default 45s) passes with
  no frame of any kind, it deregisters the daemon from the hub so the next
  dispatch doesn't try (and silently drop against) a dead connection.

If no daemon is online for a runtime at dispatch time, the trigger is no
longer failed instantly. It's queued in `WsHub._pending` and redelivered the
next time a daemon registers for that runtime; only after
`FORGE_DISPATCH_REDELIVER_TTL_S` (default 300s / 5 min) with no reconnect
does the run get marked failed via `mark_dispatch_dropped`. All three
intervals are env-configurable, not hardcoded.

## Supervision (auto-restart on crash)

### macOS (launchd) — manual setup

Create `~/Library/LaunchAgents/com.agentira.daemon.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.agentira.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/agentira</string>
        <string>daemon</string>
        <string>start</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/agentira-daemon.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/agentira-daemon.stderr.log</string>
</dict>
</plist>
```

Load it:
```bash
launchctl load ~/Library/LaunchAgents/com.agentira.daemon.plist
```

### Linux (systemd)

Create `~/.config/systemd/user/agentira-daemon.service`:

```ini
[Unit]
Description=AgentIRA Daemon

[Service]
ExecStart=/usr/local/bin/agentira daemon start
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Enable:
```bash
systemctl --user enable --now agentira-daemon
```

## Monitoring from the UI

- **Runtimes page** (`/forge/runtimes`): green/grey dot per runtime, grouped by daemon
- **Agents page** (`/forge/agents`): online/offline badge per agent
- **Agent detail**: runtime status indicator with green/red dot

When a dispatch is attempted with no daemon online, the run fails immediately with a "no daemon online" system message in the chat thread — no silent stall.

## In-flight registry & orphan reaping (ADR 009)

The daemon mirrors every live turn to `~/.agentira/inflight/<scope>.json`
(`trace_id`, `run_id`, `pid`, `daemon_id`). This is what makes Stop reliable
across restarts and kills the "zombie chat" class:

- **Stop-by-scope**: a cancel/pause frame carries `scope_key`; the daemon
  resolves the live turn by scope even if the in-memory trace map was lost
  (e.g. after a backend restart), and can kill by `pid` from the registry.
- **Startup reaper**: a fresh daemon owns no in-memory in-flight state, so any
  on-disk record is an orphan a prior daemon left running (claude is spawned
  `start_new_session=True`, so it survives the daemon's death). On startup the
  daemon kills each such process group and clears the record. Watch for
  `inflight reaper: N record(s) cleared` in the log right after start.
- **WS registration ack**: the backend acks the daemon's WS registration as
  the first frame; the daemon reconnects if the ack doesn't arrive, closing
  the half-open-socket "Dispatch dropped: no daemon online" dead-zone.

Inspect what the daemon thinks is live:

    ls ~/.agentira/inflight/ && cat ~/.agentira/inflight/*.json

Manual recovery for a stuck process (rare, if a registry entry is missing):
`ps -ef | grep claude` then `kill -TERM -<pgid>`.

See [ADR 009](./architecture_decision_record.md).

## Per-run environment isolation (ADR 010 / AP-308)

Each run can get its own runtime environment so concurrent runs don't collide
on the shared dev stack (the org_id / "port already in use" / migration race
class). Set per project in **Project Settings → Environment isolation**:

- **Automatic** (default) — `per_run_db` if the project declares a setup
  command, else `hermetic`.
- **No shared services (hermetic)** — the daemon strips `AGENTIRA_DB_URL` /
  `AGENTIRA_APP_DB_URL` from the run's env; the suite falls back to its own
  in-memory/file DB. Zero cost.
- **Isolated database per run (per_run_db)** — runs the project's **setup
  command** (any engine/language), which provisions the run's DB and prints
  `KEY=VALUE` connection vars (e.g. `AGENTIRA_DB_URL=…`) injected into the
  agent; the **teardown command** drops it. `$AGENTIRA_RUN_SCOPE` and
  `$AGENTIRA_DB_ADMIN_URL` are available to both. A Python project can point
  setup at `python -m backend.db --bootstrap --url $AGENTIRA_DB_URL` for exact
  schema parity.
- **Isolated full stack per run (per_run_compose)** — `docker compose -p
  run_<id> up -d --wait` (override via the setup command); `down -v` on finish.

Behavior:

- **Fail closed.** A setup non-zero/timeout fails the run with
  `environment setup failed: …` and the agent is NOT spawned — a run never
  silently falls back to shared infra.
- **Sticky-run aware.** Provision is idempotent across a run's turns; teardown
  fires only on the backend's terminal cleanup signal (same lifecycle as the
  worktree), so a paused/idle run keeps its env.
- **Crash-safe.** The teardown ctx is persisted in the inflight record; the
  startup reaper tears down orphaned envs after a daemon crash.

Common gotcha: **hermetic but the suite genuinely needs a DB** → the suite
fails on its own missing-DB error (correct signal). Switch the project to
*Isolated database per run* and set its setup command.

Timeouts: `AGENTIRA_ENV_SETUP_TIMEOUT` (default 300s),
`AGENTIRA_ENV_TEARDOWN_TIMEOUT` (default 120s).

See [ADR 010](./architecture_decision_record.md).
