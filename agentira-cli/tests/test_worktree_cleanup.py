"""AP-123: daemon-side per-run worktree cleanup.

When the backend's trigger-complete response carries cleanup_worktree +
cleanup_branch, the daemon runs `git worktree remove --force` + `git
branch -D`. Best-effort — failures are logged, never raised.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from unittest import mock

import pytest

from agentira_cli.daemon.core import AgentiraDaemon
from agentira_cli.state.config import DaemonConfig


def _daemon() -> AgentiraDaemon:
    return AgentiraDaemon(DaemonConfig())


@pytest.fixture
def repo_with_worktree():
    """A real git repo with a per-run worktree on a real branch — gives
    us something `git worktree remove` can actually remove."""
    with tempfile.TemporaryDirectory() as src:
        subprocess.run(["git", "init", "-q", src], check=True)
        subprocess.run(["git", "-C", src, "config", "user.email", "t@t"],
                       check=True)
        subprocess.run(["git", "-C", src, "config", "user.name", "t"],
                       check=True)
        subprocess.run(["git", "-C", src, "commit", "--allow-empty",
                        "-q", "-m", "init"], check=True)
        with tempfile.TemporaryDirectory() as parent:
            worktree = os.path.join(parent, "run-abc123")
            branch = "agent/abcdef12/run/abc12345"
            subprocess.run(
                ["git", "-C", src, "worktree", "add", "-q", "-B", branch,
                 worktree], check=True)
            yield {"src": src, "worktree": worktree, "branch": branch}


def test_cleanup_removes_worktree_dir(repo_with_worktree):
    """The whole point — after cleanup the worktree path is gone."""
    AgentiraDaemon._cleanup_worktree(
        repo_with_worktree["worktree"], repo_with_worktree["branch"],
    )
    assert not os.path.isdir(repo_with_worktree["worktree"])


def test_cleanup_removes_branch(repo_with_worktree):
    AgentiraDaemon._cleanup_worktree(
        repo_with_worktree["worktree"], repo_with_worktree["branch"],
    )
    branches = subprocess.check_output(
        ["git", "-C", repo_with_worktree["src"], "branch", "-a"],
        text=True,
    )
    assert repo_with_worktree["branch"] not in branches


def test_cleanup_is_no_op_on_missing_path():
    """No exception, no log spam when the path doesn't exist."""
    AgentiraDaemon._cleanup_worktree("/tmp/does-not-exist-x9k", "stale/branch")
    # Reaching here without raising is the assertion.


def test_cleanup_is_no_op_on_empty_inputs():
    AgentiraDaemon._cleanup_worktree("", "")
    AgentiraDaemon._cleanup_worktree("/tmp", "")


def test_cleanup_swallows_subprocess_errors():
    """Best-effort contract: a git failure must not propagate."""
    with mock.patch("subprocess.run",
                    side_effect=subprocess.CalledProcessError(1, "git")):
        with tempfile.TemporaryDirectory() as td:
            # Should not raise.
            AgentiraDaemon._cleanup_worktree(td, "some/branch")
