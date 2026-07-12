"""agentira daemon {start,stop,restart,status,logs}"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys

import typer

from agentira_cli.state.config import DaemonConfig
from agentira_cli.state.paths import (
    CREDENTIALS_FILE, DAEMON_ID_FILE, DAEMON_LOG_FILE, DAEMON_META_FILE,
    DAEMON_PID_FILE, HOME, ensure_home,
)

app = typer.Typer(help="Manage the AgentIRA local daemon process.")

# Isolated state dir for the test daemon, so its pid/creds/logs never collide
# with the prod daemon. Overridable; the backend URL + key are NOT hardcoded —
# they come from the environment (see the callback below).
_TEST_HOME = os.environ.get("AGENTIRA_TEST_HOME", "~/.agentira-test")


# Developer-only ergonomics (isolated test daemon home) are gated on this env
# var. Customers WON'T set it — there's no reason to — so for them there is no
# test/prod concept: `agentira daemon <cmd>` simply acts on their one configured
# daemon. Unset AGENTIRA_DEV_MODE to target ~/.agentira instead of ~/.agentira-test.
#
# This flag is NOT a security boundary; it only changes LOCAL CLI ergonomics.
# The real gate is server-side: the auth bypass lives on the backend
# (AGENTIRA_ENV=dev + AGENTIRA_DEV_API_KEY), which prod/customer backends never
# set — so a customer who flips this on just gets a test mode that can't
# connect to anything, never any prod access. Config, not code: portable across
# laptop / Railway / AWS, fail-safe OFF where unset.
_DEV = os.getenv("AGENTIRA_DEV_MODE", "").strip().lower() in ("1", "true", "yes", "on")


@app.callback()
def _daemon_main(
    ctx: typer.Context,
) -> None:
    """Manage the AgentIRA local daemon (start, stop, restart, status, logs)."""
    if not _DEV:
        return

    # ── Developer mode: isolated test home unless AGENTIRA_HOME already set ─
    # Read the test backend from AGENTIRA_TEST_API_URL / AGENTIRA_TEST_API_KEY,
    # NOT the generic AGENTIRA_DAEMON_* — those are what DaemonConfig reads, so
    # exporting them in your shell profile would also retarget the PROD daemon.
    # The dev-scoped vars are safe to keep permanently in your profile; we map
    # them onto AGENTIRA_DAEMON_* only inside the re-exec'd test child.
    if os.environ.get("AGENTIRA_HOME"):
        return
    test_url = os.environ.get("AGENTIRA_TEST_API_URL")
    test_key = os.environ.get("AGENTIRA_TEST_API_KEY")
    # start/restart actually connect and register runtimes, so they need the
    # backend URL + dev key. We never hardcode those (especially the key) —
    # read them from the env, and if they're unset, say exactly what to set.
    if ctx.invoked_subcommand in ("start", "restart"):
        missing = [n for n, v in (("AGENTIRA_TEST_API_URL", test_url),
                                   ("AGENTIRA_TEST_API_KEY", test_key)) if not v]
        if missing:
            typer.secho(
                "TEST daemon needs your local backend in the environment, but "
                "these are unset:\n  " + "\n  ".join(missing) + "\n\n"
                "Set them in ~/.agentira/.env (or export in your shell), e.g.:\n"
                "  AGENTIRA_TEST_API_URL=http://localhost:8111\n"
                "  AGENTIRA_TEST_API_KEY=<dev key>   "
                "# matches AGENTIRA_DEV_API_KEY on the backend\n\n"
                "Then re-run. (To act on your real daemon instead, unset "
                "AGENTIRA_DEV_MODE in ~/.agentira/.env.)",
                fg="yellow", err=True,
            )
            raise typer.Exit(1)
    # HOME is resolved at import time, so re-exec into the test home. The
    # AGENTIRA_HOME guard above prevents an exec loop after re-exec.
    env = os.environ.copy()
    env["AGENTIRA_HOME"] = os.path.expanduser(_TEST_HOME)
    if test_url:
        env["AGENTIRA_DAEMON_API_URL"] = test_url
    if test_key:
        env["AGENTIRA_DAEMON_API_KEY"] = test_key
    os.execvpe(sys.argv[0], sys.argv, env)


# ── Browser-based admin login ────────────────────────────────────────────

def _post_json(url: str, body: dict) -> dict:
    import urllib.request
    from agentira_cli.transport.tls import ssl_context
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as r:
        return json.loads(r.read().decode())


def load_credentials() -> dict | None:
    """Token saved by `agentira daemon login`, if any."""
    if CREDENTIALS_FILE.exists():
        try:
            return json.loads(CREDENTIALS_FILE.read_text())
        except (ValueError, OSError):
            return None
    return None


@app.command()
def login(api_url: str = typer.Option(None, "--api-url",
          help="Server API URL (defaults to AGENTIRA_DAEMON_API_URL/config).")):
    """Connect this daemon by signing in as an ADMIN in your browser."""
    import time
    import webbrowser
    ensure_home()
    base = (api_url or DaemonConfig().api_url).rstrip("/")
    try:
        start = _post_json(f"{base}/api/auth/cli/start", {})
    except Exception as e:  # noqa: BLE001
        typer.echo(f"Could not reach server at {base}: {e}")
        raise typer.Exit(1)

    user_code = start["user_code"]
    device_code = start["device_code"]
    verify = start.get("verification_uri") or ""
    if not verify.startswith("http"):
        # The server didn't return an absolute frontend URL (FRONTEND_URL /
        # CORS_ALLOW_ORIGINS unset on that backend). We can't reliably open a
        # relative path — point the user at the right place explicitly.
        typer.echo(f"Server at {base} didn't return a usable verification URL "
                   f"(got '{verify or 'nothing'}').")
        typer.echo("If you meant the hosted product, re-run with:")
        typer.echo("  agentira daemon login --api-url https://flowty-api-production.up.railway.app")
        raise typer.Exit(1)
    url = f"{verify}?user_code={user_code}"
    typer.echo("Opening your browser to authorize this daemon (sign in as an admin)…")
    typer.echo(f"  URL:  {url}")
    typer.echo(f"  Code: {user_code}")
    opened = False
    try:
        opened = webbrowser.open(url)
    except Exception:  # noqa: BLE001
        opened = False
    if not opened:
        typer.echo("  (couldn't auto-open a browser — paste the URL above manually)")

    interval = int(start.get("interval", 2))
    deadline = time.time() + int(start.get("expires_in", 600))
    token = None
    typer.echo("Waiting for approval…")
    while time.time() < deadline:
        time.sleep(interval)
        try:
            r = _post_json(f"{base}/api/auth/cli/poll", {"device_code": device_code})
        except Exception:  # noqa: BLE001 — keep polling on transient errors
            continue
        if r.get("status") == "approved" and r.get("token"):
            token = r["token"]
            break
    if not token:
        typer.echo("Login timed out. Run `agentira daemon login` again.")
        raise typer.Exit(1)

    CREDENTIALS_FILE.write_text(json.dumps({"api_url": base, "token": token}))
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except OSError:
        pass
    typer.echo("✓ Daemon authorized. You can now run `agentira daemon start`.")


@app.command()
def logout():
    """Remove stored daemon credentials."""
    try:
        CREDENTIALS_FILE.unlink()
        typer.echo("Logged out.")
    except FileNotFoundError:
        typer.echo("Not logged in.")


def _read_pid() -> int | None:
    if DAEMON_PID_FILE.exists():
        try:
            return int(DAEMON_PID_FILE.read_text().strip())
        except ValueError:
            pass
    return None


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# Implementation helpers — plain functions, NOT typer commands. Restart
# calls these directly so we never invoke a decorated typer function from
# inside another command (which can reenter typer's option-parsing and
# block waiting on stdin/argv on some Python builds — observed as a
# permanently-hung `agentira daemon restart` process).

def _start_impl(*, dry_run: bool, foreground: bool, api_key: str | None) -> None:
    """Core start logic. Returns immediately when foreground=False
    (background fork) or blocks forever when foreground=True."""
    ensure_home()

    pid = _read_pid()
    if pid and _is_running(pid):
        typer.echo(f"Daemon already running (PID {pid}).")
        return

    config = DaemonConfig()
    # Explicit reset of dry_run unless explicitly requested. Prevents the
    # "comes back in dry_run=True silently" bug where DaemonConfig picked
    # up a leftover env var or config-file value from a prior invocation.
    config.dry_run = bool(dry_run)
    if api_key:
        config.api_key = api_key
    elif not config.api_key:
        # Fall back to the admin token from `agentira daemon login`.
        creds = load_credentials()
        if creds and creds.get("token"):
            config.api_key = creds["token"]
            if creds.get("api_url"):
                config.api_url = creds["api_url"]
    if not config.api_key:
        typer.echo("Not authorized. Run `agentira daemon login` first "
                   "(sign in as an admin).")
        return

    # Record what this daemon is for, so `status` can show which one it is
    # (e.g. local test vs prod) when several daemons coexist via AGENTIRA_HOME.
    DAEMON_META_FILE.write_text(json.dumps({
        "api_url": config.api_url, "dry_run": bool(config.dry_run)}))

    if foreground:
        _run_daemon(config)
        return

    import subprocess
    cmd = [sys.executable, "-m", "agentira_cli.daemon._entry"]
    env = os.environ.copy()
    env.update({
        "AGENTIRA_DAEMON_API_KEY": config.api_key or "",
        "AGENTIRA_DAEMON_API_URL": config.api_url,
        "AGENTIRA_DAEMON_DRY_RUN": "true" if config.dry_run else "false",
    })
    # Open the log file just long enough to hand its fd to the child;
    # closing in the parent avoids dangling FDs on long-lived sessions.
    log = open(DAEMON_LOG_FILE, "a")
    try:
        proc = subprocess.Popen(
            cmd, env=env, stdout=log, stderr=log, start_new_session=True,
        )
    finally:
        log.close()
    DAEMON_PID_FILE.write_text(str(proc.pid))
    typer.echo(f"Daemon started (PID {proc.pid}) — home {HOME}")
    typer.echo(f"  backend {config.api_url}  ·  logs {DAEMON_LOG_FILE}")


def _stop_impl() -> bool:
    """Stop the daemon. Returns True if a daemon was running and was signalled."""
    pid = _read_pid()
    if not pid or not _is_running(pid):
        DAEMON_PID_FILE.unlink(missing_ok=True)
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    DAEMON_PID_FILE.unlink(missing_ok=True)
    return True


def _restart_impl(*, dry_run: bool = False, api_key: str | None = None) -> None:
    """Stop + start in one call. Always backgrounds the new daemon.

    Plain function so the typer-command `restart()` doesn't recursively
    invoke decorated commands — which historically blocked the parent
    process forever.
    """
    stopped = _stop_impl()
    if stopped:
        typer.echo("Stopped previous daemon.")
        import time
        time.sleep(1)
    _start_impl(dry_run=dry_run, foreground=False, api_key=api_key)


@app.command("start")
def start(
    dry_run: bool = typer.Option(False, "--dry-run", help="Log actions, skip executor"),
    background: bool = typer.Option(False, "--background", "-b", help="Run in background (default: foreground)"),
    api_key: str = typer.Option(None, "--api-key", help="Daemon auth token (optional)"),
) -> None:
    """Start the daemon (foreground by default)."""
    _start_impl(dry_run=dry_run, foreground=not background, api_key=api_key)


@app.command("stop")
def stop() -> None:
    """Stop the running daemon."""
    stopped = _stop_impl()
    if stopped:
        typer.echo(f"Stopped daemon at {HOME}.")
    else:
        typer.echo(f"No daemon running at {HOME}.")


@app.command("restart")
def restart(
    dry_run: bool = typer.Option(False, "--dry-run", help="Log actions, skip executor"),
    api_key: str = typer.Option(None, "--api-key", help="Daemon auth token (optional)"),
) -> None:
    """Stop then start the daemon."""
    _restart_impl(dry_run=dry_run, api_key=api_key)


def _probe_ws_connected(api_url: str, daemon_id: str) -> bool | None:
    """Ask the backend whether this daemon's WS is currently connected.

    Returns True/False, or None if the backend is unreachable.
    """
    import urllib.request
    import urllib.error
    url = f"{api_url.rstrip('/')}/api/forge/runtimes"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            runtimes = json.loads(resp.read())
        return any(
            rt.get("daemon_id") == daemon_id and rt.get("status") == "online"
            for rt in runtimes
        )
    except Exception:
        return None


@app.command("status")
def status(output: str = typer.Option("text", "--output", "-o", help="text | json")) -> None:
    """Show daemon status — actual process state, not just the pid file."""
    pid = _read_pid()
    daemon_id = DAEMON_ID_FILE.read_text().strip() if DAEMON_ID_FILE.exists() else None
    running = bool(pid and _is_running(pid))

    # Surface dry_run flag from env if the process is running. Helps catch
    # the "daemon comes back in dry_run=True silently" case.
    dry_run_env = os.environ.get("AGENTIRA_DAEMON_DRY_RUN", "").lower() in ("1", "true", "yes")

    # If pid file is stale (points at a dead pid), say so explicitly.
    stale_pid_file = bool(pid and not running)

    meta = {}
    try:
        meta = json.loads(DAEMON_META_FILE.read_text())
    except Exception:
        meta = {}

    # Probe the daemon's OWN backend (recorded in meta) for WS state.
    ws_connected: bool | None = None
    if running and daemon_id:
        backend = meta.get("api_url") or DaemonConfig().api_url
        ws_connected = _probe_ws_connected(backend, daemon_id)

    from agentira_cli._version import get_version
    from agentira_cli.state.paths import UPDATE_CHECK_CACHE_FILE
    cli_version = get_version()
    update_hint = ""
    try:
        cache = json.loads(UPDATE_CHECK_CACHE_FILE.read_text())
        latest = cache.get("latest")
        if latest:
            from agentira_cli.update_check import is_newer
            if is_newer(str(latest), cli_version):
                update_hint = str(latest)
    except (OSError, ValueError, TypeError):
        pass

    data = {
        "home": str(HOME),
        "home_overridden": bool(os.environ.get("AGENTIRA_HOME")),
        "backend": meta.get("api_url"),
        "running": running,
        "pid": pid if running else None,
        "stale_pid_file": stale_pid_file,
        "daemon_id": daemon_id,
        "dry_run_env": dry_run_env,
        "ws_connected": ws_connected,
        "log": str(DAEMON_LOG_FILE),
        "cli_version": cli_version,
        "update_available": update_hint or None,
    }

    if output == "json":
        typer.echo(json.dumps(data, indent=2))
    else:
        state = f"running (PID {pid})" if running else "stopped"
        if stale_pid_file:
            state = f"stopped (stale pid file points at dead PID {pid})"
        home_note = "  (AGENTIRA_HOME)" if os.environ.get("AGENTIRA_HOME") else "  (default)"
        typer.echo(f"Home:      {HOME}{home_note}")
        if meta.get("api_url"):
            typer.echo(f"Backend:   {meta['api_url']}")
        typer.echo(f"Status:    {state}")
        if daemon_id:
            typer.echo(f"Daemon ID: {daemon_id}")
        if running and ws_connected is True:
            typer.echo("WebSocket: connected")
        elif running and ws_connected is False:
            typer.echo("WebSocket: DISCONNECTED (daemon running but backend has no active WS)")
        elif running and ws_connected is None:
            typer.echo("WebSocket: unconfirmed (status probe is unauthenticated; "
                       "the daemon may well be connected — see `daemon logs`)")
        if dry_run_env:
            typer.echo("Mode:      DRY-RUN (env var set — triggers won't spawn subprocesses)")
        typer.echo(f"CLI:       agentira-cli {cli_version}")
        if update_hint:
            typer.echo(f"Update:    {update_hint} available — run `agentira daemon update`")
        typer.echo(f"Log:       {DAEMON_LOG_FILE}")


@app.command("version")
def version_cmd() -> None:
    """Show the installed agentira-cli version."""
    from agentira_cli._version import get_version
    typer.echo(f"agentira-cli {get_version()}")


@app.command("update")
def update_cmd(
    check_only: bool = typer.Option(False, "--check", help="Only check for updates"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Install without prompting"),
    restart: bool = typer.Option(False, "--restart", help="Restart daemon after a successful update"),
) -> None:
    """Upgrade agentira-cli from your Agentira instance (pip install wheel).

    Uses the same Python as this command, so launchd/systemd services
    pick up the upgrade after `daemon restart`. No manual pip needed.
    """
    from agentira_cli.update_check import run_update

    api_url = DaemonConfig().api_url
    if check_only:
        result = run_update(api_url=api_url, check_only=True)
        typer.echo(result["message"])
        raise typer.Exit(0)

    result = run_update(api_url=api_url, yes=False)
    if result.get("message") == "confirmation_required":
        latest = result["latest"]
        current = result["current"]
        typer.echo(f"Update available: {current} → {latest}")
        if not typer.confirm("Install now?", default=True):
            typer.echo("Cancelled.")
            raise typer.Exit(0)
        result = run_update(api_url=api_url, yes=True)

    typer.echo(result.get("message") or "Done.")
    if not result.get("updated"):
        raise typer.Exit(1 if result.get("latest") else 0)

    if restart:
        typer.echo("Restarting daemon…")
        _restart_impl()
    else:
        typer.echo("Restart the daemon to load the new code: `agentira daemon restart`")


@app.command("logs")
def logs(
    follow: bool = typer.Option(False, "-f", "--follow", help="Follow log output"),
    lines: int = typer.Option(50, "-n", "--lines", help="Number of lines to show"),
) -> None:
    """Show daemon logs."""
    if not DAEMON_LOG_FILE.exists():
        typer.echo("No log file found.")
        raise typer.Exit(0)

    if follow:
        import subprocess
        subprocess.run(["tail", f"-n{lines}", "-f", str(DAEMON_LOG_FILE)])
    else:
        import subprocess
        subprocess.run(["tail", f"-n{lines}", str(DAEMON_LOG_FILE)])


_LAUNCHD_LABEL = "com.agentira.daemon"
_LAUNCHD_PLIST_DIR = os.path.expanduser("~/Library/LaunchAgents")


@app.command("install-launchd")
def install_launchd() -> None:
    """Install a macOS launchd plist so the daemon auto-restarts on crash/login."""
    if sys.platform != "darwin":
        typer.echo("Error: install-launchd is macOS-only. Use systemd on Linux.", err=True)
        raise typer.Exit(1)

    import shutil
    agentira_bin = shutil.which("agentira")
    if not agentira_bin:
        typer.echo("Error: 'agentira' not found in PATH.", err=True)
        raise typer.Exit(1)

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{agentira_bin}</string>
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
"""
    os.makedirs(_LAUNCHD_PLIST_DIR, exist_ok=True)
    plist_path = os.path.join(_LAUNCHD_PLIST_DIR, f"{_LAUNCHD_LABEL}.plist")
    with open(plist_path, "w") as f:
        f.write(plist_content)

    import subprocess
    subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
    subprocess.run(["launchctl", "load", plist_path], check=True)
    typer.echo(f"Installed and loaded: {plist_path}")
    typer.echo("The daemon will now auto-restart on crash and start on login.")
    typer.echo(f"To uninstall: launchctl unload {plist_path} && rm {plist_path}")


@app.command("uninstall-launchd")
def uninstall_launchd() -> None:
    """Remove the launchd plist (stops auto-restart)."""
    if sys.platform != "darwin":
        typer.echo("Error: macOS only.", err=True)
        raise typer.Exit(1)

    plist_path = os.path.join(_LAUNCHD_PLIST_DIR, f"{_LAUNCHD_LABEL}.plist")
    if not os.path.exists(plist_path):
        typer.echo("No plist installed.")
        raise typer.Exit(0)

    import subprocess
    subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
    os.remove(plist_path)
    typer.echo(f"Removed: {plist_path}")


@app.command("install-openclaw-mcps")
def install_openclaw_mcps(
    api_key: str = typer.Option(..., "--api-key", help="Agentira bot API key (Profile → Copy bot key)"),
    repo_path: str = typer.Option("", "--repo-path", help="Project repo root for the agentira-project MCP server"),
    mcp_url: str = typer.Option("http://localhost:8000/mcp", "--mcp-url", help="Agentira MCP HTTP URL"),
    openclaw_bin: str = typer.Option("openclaw", "--openclaw-bin", help="Path to the openclaw binary"),
) -> None:
    """AP-103: seed Agentira's MCP servers into OpenClaw's config.

    OpenClaw's chat-completions endpoint can't take per-call MCP config, so
    MCP must live in OpenClaw's own config. This registers `agentira`,
    `memory`, and `agentira-project` so OpenClaw-hosted agents (Qwen, Kimi)
    get the same tools as Claude agents.

    This command is a one-time SEED / verification step. At runtime the
    daemon overwrites these entries per-dispatch with the dispatched
    agent's own token + memory path, so identity stays per-agent — you
    don't need to re-run this per agent.
    """
    from agentira_cli.runtimes.openclaw import register_agentira_mcps

    servers: dict = {
        "agentira": {
            "type": "http",
            "url": mcp_url,
            "headers": {"Authorization": f"Bearer {api_key}"},
        },
        "memory": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-memory"],
        },
    }
    if repo_path:
        servers["agentira-project"] = {
            "command": "python3",
            "args": ["-m", "agentira_cli.mcp.agentira_project"],
            "env": {"AGENTIRA_REPO_PATH": repo_path},
        }

    result = register_agentira_mcps({"mcpServers": servers}, binary_path=openclaw_bin)
    for name in result["registered"]:
        typer.echo(f"  ✓ {name}")
    for f in result["failed"]:
        typer.echo(f"  ✗ {f['name']}: {f['error']}", err=True)
    if result["failed"]:
        raise typer.Exit(1)
    typer.echo(
        f"Registered {len(result['registered'])} MCP server(s) into OpenClaw. "
        "Restart OpenClaw for the runner agent to pick them up."
    )


def _run_daemon(config: DaemonConfig) -> None:
    """Run daemon in foreground (blocking)."""
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(str(DAEMON_LOG_FILE)),
            logging.StreamHandler(sys.stderr),
        ],
    )
    DAEMON_PID_FILE.write_text(str(os.getpid()))
    try:
        from agentira_cli.daemon.core import AgentiraDaemon
        AgentiraDaemon(config).run()
    finally:
        DAEMON_PID_FILE.unlink(missing_ok=True)
