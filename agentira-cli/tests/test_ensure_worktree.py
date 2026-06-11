"""_ensure_worktree robustness (multi-repo provisioning).

Covers the two silent-failure modes that stranded a frontend task in a
backend worktree:
  1. source-not-found (e.g. a non-absolute/typo'd repo_path) — must report a
     reason instead of silently no-op'ing.
  2. wrong-source reuse — an existing worktree from a DIFFERENT source repo
     (task's repo_name changed, or a stale prior run) must be removed and
     recreated off the correct source, not silently reused.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

import pytest

from agentira_cli.daemon.core import _ensure_worktree


def _init_repo(path: str, marker: str) -> None:
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "t"], check=True)
    # A marker file unique per repo so we can tell which source a worktree came from.
    with open(os.path.join(path, marker), "w") as f:
        f.write(marker)
    subprocess.run(["git", "-C", path, "add", "."], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", "init"], check=True)


@pytest.fixture
def two_repos():
    with tempfile.TemporaryDirectory() as root:
        backend = os.path.join(root, "backend")
        frontend = os.path.join(root, "frontend")
        _init_repo(backend, "BACKEND_MARKER")
        _init_repo(frontend, "FRONTEND_MARKER")
        target = os.path.join(root, "agent-home", "task-x")
        yield {"backend": backend, "frontend": frontend, "target": target}


def test_creates_fresh_worktree(two_repos):
    reason = _ensure_worktree(
        source=two_repos["frontend"], target=two_repos["target"],
        branch="agent/x/task/y",
    )
    assert reason == "ok"
    assert os.path.exists(os.path.join(two_repos["target"], "FRONTEND_MARKER"))


def test_reuses_matching_worktree(two_repos):
    args = dict(source=two_repos["frontend"], target=two_repos["target"],
                branch="agent/x/task/y")
    assert _ensure_worktree(**args) == "ok"
    # Second call with the same source → reused, not recreated.
    assert _ensure_worktree(**args) == "ok"
    assert os.path.exists(os.path.join(two_repos["target"], "FRONTEND_MARKER"))


def test_recreates_on_source_mismatch(two_repos):
    """The exact f8c42d0d bug: a worktree built off the BACKEND repo must be
    replaced when the task is (re)dispatched against the FRONTEND repo."""
    # First provisioned (wrongly) off backend.
    _ensure_worktree(source=two_repos["backend"], target=two_repos["target"],
                     branch="agent/x/task/y")
    assert os.path.exists(os.path.join(two_repos["target"], "BACKEND_MARKER"))
    # Re-dispatch off frontend → must detect the mismatch and recreate.
    reason = _ensure_worktree(source=two_repos["frontend"],
                              target=two_repos["target"], branch="agent/x/task/y")
    assert reason == "worktree_recreated_source_mismatch"
    assert os.path.exists(os.path.join(two_repos["target"], "FRONTEND_MARKER"))
    assert not os.path.exists(os.path.join(two_repos["target"], "BACKEND_MARKER"))


def test_source_not_found_is_reported_not_silent(two_repos):
    # A relative / typo'd path (the dropped-leading-slash bug).
    reason = _ensure_worktree(source="Users/me/frontend",
                              target=two_repos["target"], branch="agent/x/task/y")
    assert reason.startswith("worktree_source_not_found:")
    assert not os.path.exists(two_repos["target"])


def test_no_source_or_branch_is_noop(two_repos):
    assert _ensure_worktree(source="", target=two_repos["target"], branch="b") == ""
    assert _ensure_worktree(source=two_repos["frontend"],
                            target=two_repos["target"], branch="") == ""


def test_clears_non_worktree_leftover_before_add(two_repos):
    """AP-237 follow-up: the dispatch loop calls makedirs(target) and writes
    `.agentira/CONVENTIONS.md` BEFORE _ensure_worktree. A prior crash/abort
    can leave the target dir populated (with .agentira/, AGENTS.md symlink,
    etc.) but without a `.git` file — not a registered worktree. `git
    worktree add` then refuses with 'fatal: <path> already exists'. The
    cleanup must remove the non-worktree leftover and the add must succeed."""
    target = two_repos["target"]
    # Simulate the partial-materialization residue.
    os.makedirs(os.path.join(target, ".agentira"), exist_ok=True)
    with open(os.path.join(target, ".agentira", "CONVENTIONS.md"), "w") as f:
        f.write("# project conventions\n")
    os.symlink(".agentira/CONVENTIONS.md",
               os.path.join(target, "AGENTS.md"))
    assert not os.path.exists(os.path.join(target, ".git"))
    reason = _ensure_worktree(
        source=two_repos["frontend"], target=target, branch="agent/x/task/y",
    )
    assert reason == "ok"
    # Worktree-add succeeded → target is a real worktree off frontend.
    assert os.path.exists(os.path.join(target, ".git"))
    assert os.path.exists(os.path.join(target, "FRONTEND_MARKER"))
