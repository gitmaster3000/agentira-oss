"""AP-240: chmod 0700 on agent home dirs — daemon-side isolation hardening.

Architecture stays put (one shared source clone per project, per-task
worktrees branched off it — that's load-bearing for review→merge). This
fix closes the easy cross-agent filesystem read: agent A can no longer
`cat ~/.agentira/agents/<B>/...`.
"""

from __future__ import annotations

import os
import stat
import sys

import pytest

from agentira_cli.daemon import isolation


@pytest.fixture
def home(monkeypatch, tmp_path):
    """Pin the user's home so the lockdown writes under tmp, not the real
    ~/.agentira. Works regardless of whether the module uses HOME, USERPROFILE,
    or Path.home() — we monkeypatch the env var that drives expanduser."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _mode_of(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.mark.skipif(sys.platform.startswith("win"),
                    reason="POSIX mode bits don't apply on Windows")
def test_lockdown_creates_dir_with_mode_700(home):
    assert isolation.lockdown_agent_home("agent-A") is True
    root = home / ".agentira" / "agents" / "agent-A"
    assert root.is_dir()
    assert _mode_of(str(root)) == 0o700


@pytest.mark.skipif(sys.platform.startswith("win"),
                    reason="POSIX mode bits don't apply on Windows")
def test_lockdown_is_idempotent(home):
    """Re-dispatch on the same agent must succeed without error and leave
    the mode as 0700, even if previous dispatches already created the
    dir."""
    assert isolation.lockdown_agent_home("agent-A") is True
    # Second call — should pass cleanly, not raise.
    assert isolation.lockdown_agent_home("agent-A") is True
    root = home / ".agentira" / "agents" / "agent-A"
    assert _mode_of(str(root)) == 0o700


@pytest.mark.skipif(sys.platform.startswith("win"),
                    reason="POSIX mode bits don't apply on Windows")
def test_lockdown_chmods_home_subdir_if_present(home):
    """Once the dispatcher has provisioned `<root>/home/`, the hardening
    must reach into it too — the materializer lays out `home/repos/...`
    and we want that under 0700 regardless of which dir is chmodded
    first."""
    agent_root = home / ".agentira" / "agents" / "agent-A"
    agent_root.mkdir(parents=True)
    home_sub = agent_root / "home"
    home_sub.mkdir()
    # Pre-existing wide-open perms to verify they get tightened.
    os.chmod(home_sub, 0o755)
    assert isolation.lockdown_agent_home("agent-A") is True
    assert _mode_of(str(home_sub)) == 0o700


def test_lockdown_empty_agent_id_returns_false(home):
    """Defensive: empty/None agent_id must not silently touch the home dir
    at all (degenerate input — caller failed upstream)."""
    assert isolation.lockdown_agent_home("") is False
    assert not (home / ".agentira" / "agents").exists()


@pytest.mark.skipif(sys.platform.startswith("win"),
                    reason="POSIX mode bits don't apply on Windows")
def test_lockdown_returns_false_on_os_error(home, monkeypatch):
    """A real OSError must be logged and surface as False — never raise.
    The hardening layer must not break a dispatch when the FS is wonky
    (read-only mount, ACL conflict, etc.)."""
    def _boom(*a, **k):
        raise OSError("simulated permission denied")
    monkeypatch.setattr(isolation.os, "chmod", _boom)
    assert isolation.lockdown_agent_home("agent-A") is False


@pytest.mark.skipif(not sys.platform.startswith("win"),
                    reason="Windows-specific skip path")
def test_lockdown_skipped_on_windows(home):
    """POSIX mode bits don't apply on Windows — function returns True
    without doing anything."""
    assert isolation.lockdown_agent_home("agent-A") is True
