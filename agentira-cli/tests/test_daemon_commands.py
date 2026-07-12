"""Tests for the daemon CLI commands — the pieces that were causing
stuck `agentira daemon restart` processes, stale pid files, and the
dry_run-comes-back-set bug.

We don't actually spawn a daemon here. We mock subprocess.Popen and
verify the command flow: pid file lifecycle, signal sending, restart
sequencing. The point is to catch regressions where calling
`_restart_impl()` accidentally blocks or `_start_impl()` doesn't reset
dry_run."""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path
from unittest import mock

import pytest


# ── shared fixtures ──────────────────────────────────────────────────────


@pytest.fixture()
def temp_state(tmp_path, monkeypatch):
    """Redirect ~/.agentira/* to tmp_path so tests don't touch real state."""
    home = tmp_path / "agentira"
    home.mkdir()
    pid_file = home / "daemon.pid"
    log_file = home / "daemon.log"
    id_file = home / "daemon.id"

    # The paths module exports module-level Path constants — we patch them.
    monkeypatch.setattr(
        "agentira_cli.state.paths.DAEMON_PID_FILE", pid_file, raising=True,
    )
    monkeypatch.setattr(
        "agentira_cli.state.paths.DAEMON_LOG_FILE", log_file, raising=True,
    )
    monkeypatch.setattr(
        "agentira_cli.state.paths.DAEMON_ID_FILE", id_file, raising=True,
    )
    # `commands.daemon` imported these names at module load → patch in place too.
    monkeypatch.setattr(
        "agentira_cli.commands.daemon.DAEMON_PID_FILE", pid_file, raising=True,
    )
    monkeypatch.setattr(
        "agentira_cli.commands.daemon.DAEMON_LOG_FILE", log_file, raising=True,
    )
    monkeypatch.setattr(
        "agentira_cli.commands.daemon.DAEMON_ID_FILE", id_file, raising=True,
    )
    monkeypatch.setattr(
        "agentira_cli.commands.daemon.ensure_home", lambda: None, raising=True,
    )
    return {"home": home, "pid": pid_file, "log": log_file, "id": id_file}


# ── _start_impl ──────────────────────────────────────────────────────────


def test_pair_command_calls_ensure_registered(temp_state, monkeypatch):
    from agentira_cli.commands import daemon
    from agentira_cli.runtimes.openclaw_device import generate_identity

    called = {}

    def fake_ensure(**kwargs):
        called.update(kwargs)
        ident = generate_identity(gateway_url="http://127.0.0.1:18789")
        ident.device_token = "t"
        ident.scopes = ["operator.read", "operator.write"]
        return ident

    monkeypatch.setattr(
        "agentira_cli.runtimes.openclaw_device.ensure_registered",
        fake_ensure,
    )
    monkeypatch.setattr(
        "agentira_cli.runtimes.openclaw.OpenClawRuntime.introspect",
        classmethod(lambda cls, binary_path="openclaw": {
            "gateway_url": "http://127.0.0.1:18789",
            "gateway_token": "gw",
        }),
    )
    daemon.pair(force=True)
    assert called.get("force") is True
    assert called.get("gateway_token") == "gw"


def test_start_background_returns_immediately(temp_state, monkeypatch):
    """Background start must return within 1s — historic hang was waiting
    forever on the subprocess. Failure mode: restart() never returns."""
    from agentira_cli.commands import daemon

    fake_proc = mock.MagicMock()
    fake_proc.pid = 12345

    popen_called = threading.Event()

    def _fake_popen(cmd, env=None, stdout=None, stderr=None, start_new_session=None):
        popen_called.set()
        return fake_proc

    monkeypatch.setattr("subprocess.Popen", _fake_popen)

    started = time.time()
    daemon._start_impl(dry_run=False, foreground=False, api_key=None)
    elapsed = time.time() - started

    assert elapsed < 1.0, f"start_impl took {elapsed:.2f}s — should be near-instant"
    assert popen_called.is_set(), "subprocess.Popen never called"
    assert temp_state["pid"].read_text().strip() == "12345"


def test_start_when_already_running_is_noop(temp_state, monkeypatch):
    """If pid file points at a live process, start should bail quickly
    without spawning a second daemon."""
    from agentira_cli.commands import daemon

    # Stash a fake live pid (use our own — os.kill(pid, 0) succeeds).
    temp_state["pid"].write_text(str(os.getpid()))

    popen_calls = []
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *a, **kw: popen_calls.append((a, kw)) or mock.MagicMock(pid=0),
    )

    daemon._start_impl(dry_run=False, foreground=False, api_key=None)
    assert popen_calls == [], "Should not spawn when daemon already running"


def test_start_resets_dry_run_when_false(temp_state, monkeypatch):
    """The 'comes back in dry_run=True silently' bug: env var or persisted
    config from a prior --dry-run invocation should NOT carry over when
    the user runs `agentira daemon start` without --dry-run."""
    from agentira_cli.commands import daemon

    # Pretend a leftover env var is set
    monkeypatch.setenv("AGENTIRA_DAEMON_DRY_RUN", "true")

    captured_env: dict = {}

    def _fake_popen(cmd, env=None, **kw):
        captured_env.update(env or {})
        return mock.MagicMock(pid=999)

    monkeypatch.setattr("subprocess.Popen", _fake_popen)

    daemon._start_impl(dry_run=False, foreground=False, api_key=None)

    # The env passed to the child should reflect dry_run=False, regardless
    # of the parent's pre-existing AGENTIRA_DAEMON_DRY_RUN.
    assert captured_env.get("AGENTIRA_DAEMON_DRY_RUN") == "false", \
        "dry_run leaked from env into child despite explicit dry_run=False"


# ── _stop_impl ───────────────────────────────────────────────────────────


def test_stop_no_pid_file_is_safe(temp_state):
    """No pid file → return False without raising."""
    from agentira_cli.commands import daemon

    assert daemon._stop_impl() is False


def test_stop_stale_pid_file_cleaned(temp_state):
    """Pid file pointing at a dead pid → cleaned, returns False."""
    from agentira_cli.commands import daemon

    # Use a pid that definitely doesn't exist (PID 1 is init but we'll
    # use a huge number that won't exist).
    temp_state["pid"].write_text("999999999")
    assert daemon._stop_impl() is False
    assert not temp_state["pid"].exists()


def test_stop_signals_live_pid(temp_state, monkeypatch):
    """Pid file → live process → SIGTERM is sent, pid file removed."""
    from agentira_cli.commands import daemon

    sent = []
    monkeypatch.setattr("os.kill", lambda pid, sig: sent.append((pid, sig)))
    # Force _is_running to return True regardless of real OS state
    monkeypatch.setattr(daemon, "_is_running", lambda pid: True)

    temp_state["pid"].write_text("42")
    assert daemon._stop_impl() is True
    assert (42, signal.SIGTERM) in sent
    assert not temp_state["pid"].exists()


# ── _restart_impl — THE HEADLINE TEST ────────────────────────────────────


def test_restart_returns_within_5_seconds(temp_state, monkeypatch):
    """The recurring 'agentira daemon restart hangs forever' bug. Restart
    must return quickly — this is the regression test."""
    from agentira_cli.commands import daemon

    fake_proc = mock.MagicMock()
    fake_proc.pid = 7777
    monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: fake_proc)
    # Skip the 1s sleep between stop+start
    monkeypatch.setattr("time.sleep", lambda *_: None)

    started = time.time()
    daemon._restart_impl()
    elapsed = time.time() - started

    assert elapsed < 5.0, f"restart_impl took {elapsed:.2f}s — that's the hang bug returning"


def test_restart_with_no_existing_daemon_just_starts(temp_state, monkeypatch):
    """Stop returns False (nothing to stop) → start is called → done.
    No spurious 'stop failed' errors."""
    from agentira_cli.commands import daemon

    fake_proc = mock.MagicMock()
    fake_proc.pid = 8888
    monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: fake_proc)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    daemon._restart_impl()
    assert temp_state["pid"].read_text().strip() == "8888"


# ── status truthfulness ──────────────────────────────────────────────────


def test_status_reports_stale_pid_file(temp_state, capsys):
    """Stale pid file should be called out explicitly so users don't think
    a dead daemon is alive."""
    from agentira_cli.commands import daemon

    temp_state["pid"].write_text("999999999")
    # Use the typer command runner indirectly — call the function with
    # default arg.
    daemon.status(output="text")
    out = capsys.readouterr().out
    assert "stale" in out.lower() or "stopped" in out.lower()


def test_status_surfaces_dry_run_env(temp_state, capsys, monkeypatch):
    """If AGENTIRA_DAEMON_DRY_RUN is set when status is called, the user
    needs to see it so they know triggers won't actually run."""
    from agentira_cli.commands import daemon

    monkeypatch.setenv("AGENTIRA_DAEMON_DRY_RUN", "true")
    daemon.status(output="text")
    out = capsys.readouterr().out.lower()
    assert "dry-run" in out or "dry_run" in out
