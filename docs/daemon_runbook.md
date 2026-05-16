# Daemon Operations Runbook

How to diagnose, restart, and supervise the AgentIRA daemon.

## Quick reference

```bash
agentira daemon status          # Process + WS state + dry_run flag
agentira daemon logs -f         # Tail the daemon log
agentira daemon restart         # Stop + start (detaches immediately)
agentira daemon stop            # Graceful SIGTERM
agentira daemon start           # Start in background
agentira daemon start --foreground  # Debug mode (logs to stdout)
```

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
        <string>--foreground</string>
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
ExecStart=/usr/local/bin/agentira daemon start --foreground
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
