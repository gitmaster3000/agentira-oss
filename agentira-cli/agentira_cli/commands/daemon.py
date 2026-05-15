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
    DAEMON_ID_FILE, DAEMON_LOG_FILE, DAEMON_PID_FILE, ensure_home,
)

app = typer.Typer(help="Manage the AgentIRA local daemon process.")


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
    typer.echo(f"Daemon started (PID {proc.pid}). Logs: {DAEMON_LOG_FILE}")


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
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground (default: background)"),
    api_key: str = typer.Option(None, "--api-key", help="Daemon auth token (optional)"),
) -> None:
    """Start the daemon (background by default)."""
    _start_impl(dry_run=dry_run, foreground=foreground, api_key=api_key)


@app.command("stop")
def stop() -> None:
    """Stop the running daemon."""
    stopped = _stop_impl()
    if stopped:
        typer.echo("Stopped.")
    else:
        typer.echo("Daemon is not running.")


@app.command("restart")
def restart(
    dry_run: bool = typer.Option(False, "--dry-run", help="Log actions, skip executor"),
    api_key: str = typer.Option(None, "--api-key", help="Daemon auth token (optional)"),
) -> None:
    """Stop then start the daemon."""
    _restart_impl(dry_run=dry_run, api_key=api_key)


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

    data = {
        "running": running,
        "pid": pid if running else None,
        "stale_pid_file": stale_pid_file,
        "daemon_id": daemon_id,
        "dry_run_env": dry_run_env,
        "log": str(DAEMON_LOG_FILE),
    }

    if output == "json":
        typer.echo(json.dumps(data, indent=2))
    else:
        state = f"running (PID {pid})" if running else "stopped"
        if stale_pid_file:
            state = f"stopped (stale pid file points at dead PID {pid})"
        typer.echo(f"Status:    {state}")
        if daemon_id:
            typer.echo(f"Daemon ID: {daemon_id}")
        if dry_run_env:
            typer.echo("Mode:      DRY-RUN (env var set — triggers won't spawn subprocesses)")
        typer.echo(f"Log:       {DAEMON_LOG_FILE}")


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
