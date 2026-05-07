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


@app.command("start")
def start(
    dry_run: bool = typer.Option(False, "--dry-run", help="Log actions, skip executor"),
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground (default: background)"),
    api_key: str = typer.Option(None, "--api-key", help="Daemon auth token (optional)"),
) -> None:
    """Start the daemon (background by default)."""
    ensure_home()

    pid = _read_pid()
    if pid and _is_running(pid):
        typer.echo(f"Daemon already running (PID {pid}).")
        raise typer.Exit(0)

    config = DaemonConfig()
    if dry_run:
        config.dry_run = True
    if api_key:
        config.api_key = api_key

    if foreground:
        _run_daemon(config)
    else:
        import subprocess
        cmd = [sys.executable, "-m", "agentira_cli.daemon._entry"]
        env = os.environ.copy()
        env.update({
            "AGENTIRA_DAEMON_API_KEY": config.api_key or "",
            "AGENTIRA_DAEMON_API_URL": config.api_url,
            "AGENTIRA_DAEMON_DRY_RUN": "true" if config.dry_run else "false",
        })
        log = open(DAEMON_LOG_FILE, "a")
        proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=log, start_new_session=True)
        DAEMON_PID_FILE.write_text(str(proc.pid))
        typer.echo(f"Daemon started (PID {proc.pid}). Logs: {DAEMON_LOG_FILE}")


@app.command("stop")
def stop() -> None:
    """Stop the running daemon."""
    pid = _read_pid()
    if not pid or not _is_running(pid):
        typer.echo("Daemon is not running.")
        DAEMON_PID_FILE.unlink(missing_ok=True)
        raise typer.Exit(0)
    os.kill(pid, signal.SIGTERM)
    typer.echo(f"Sent SIGTERM to PID {pid}.")
    DAEMON_PID_FILE.unlink(missing_ok=True)


@app.command("restart")
def restart() -> None:
    """Stop then start the daemon."""
    stop()
    import time; time.sleep(1)
    start()


@app.command("status")
def status(output: str = typer.Option("text", "--output", "-o", help="text | json")) -> None:
    """Show daemon status."""
    pid = _read_pid()
    daemon_id = DAEMON_ID_FILE.read_text().strip() if DAEMON_ID_FILE.exists() else None
    running = bool(pid and _is_running(pid))

    data = {
        "running": running,
        "pid": pid if running else None,
        "daemon_id": daemon_id,
        "log": str(DAEMON_LOG_FILE),
    }

    if output == "json":
        typer.echo(json.dumps(data, indent=2))
    else:
        state = f"running (PID {pid})" if running else "stopped"
        typer.echo(f"Status:    {state}")
        if daemon_id:
            typer.echo(f"Daemon ID: {daemon_id}")
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
