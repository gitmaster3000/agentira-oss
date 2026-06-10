"""Workflow slice 2 — deterministic branch integration in the shared clone.

Real git repos in tmp (no network): a bare 'remote', the shared clone via
ensure_source_clone (SOURCES_DIR monkeypatched), task branches made the same
way the daemon does (worktree off the clone).
"""

import subprocess
from pathlib import Path

import pytest

from agentira_cli.daemon import sources
from agentira_cli.daemon.integrate import integrate_branch


def _git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r.stdout


@pytest.fixture
def remote_and_sources(tmp_path, monkeypatch):
    """A seeded bare remote + isolated SOURCES_DIR. Returns the file:// url."""
    remote = tmp_path / "remotes" / "app.git"
    remote.parent.mkdir()
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", f"file://{remote}", str(seed)], check=True)
    (seed / "README.md").write_text("# app\n")
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    _git(seed, "branch", "-M", "main")
    _git(seed, "push", "-q", "origin", "main")
    monkeypatch.setattr(sources, "SOURCES_DIR", tmp_path / "sources")
    return f"file://{remote}"


def _make_task_branch(url, branch, filename, content="x\n"):
    """Branch + commit in the shared clone via a worktree (as the daemon does)."""
    clone, _ = sources.ensure_source_clone(url)
    wt = Path(clone).parent / f"wt-{branch.replace('/', '-')}"
    _git(clone, "worktree", "add", "-b", branch, str(wt))
    (wt / filename).write_text(content)
    _git(wt, "add", "-A")
    _git(wt, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", f"work on {branch}")
    return clone


def test_merge_and_push_happy_path(remote_and_sources):
    url = remote_and_sources
    clone = _make_task_branch(url, "agent/a/task/1", "feature.py")
    ok, reason = integrate_branch(source_url=url, branch="agent/a/task/1")
    assert ok, reason
    assert reason == "merged"
    # Merge commit landed on main in the clone AND the remote.
    assert "feature.py" in _git(clone, "ls-tree", "-r", "--name-only", "main")
    remote_log = _git(clone, "ls-remote", "origin", "main")
    local_main = _git(clone, "rev-parse", "main").strip()
    assert local_main in remote_log


def test_two_branches_integrate_sequentially(remote_and_sources):
    """The product coheres: branch B merges on top of A's merge."""
    url = remote_and_sources
    clone = _make_task_branch(url, "agent/a/task/1", "a.py")
    ok, _ = integrate_branch(source_url=url, branch="agent/a/task/1")
    assert ok
    _make_task_branch(url, "agent/b/task/2", "b.py")
    ok, reason = integrate_branch(source_url=url, branch="agent/b/task/2")
    assert ok, reason
    tree = _git(clone, "ls-tree", "-r", "--name-only", "main")
    assert "a.py" in tree and "b.py" in tree


def test_conflict_aborts_and_reports(remote_and_sources):
    url = remote_and_sources
    clone = _make_task_branch(url, "agent/a/task/1", "same.txt", "version A\n")
    _make_task_branch(url, "agent/b/task/2", "same.txt", "version B\n")
    ok, _ = integrate_branch(source_url=url, branch="agent/a/task/1")
    assert ok
    ok, reason = integrate_branch(source_url=url, branch="agent/b/task/2")
    assert not ok
    assert reason.startswith("merge_conflict")
    # Clone left clean on main — no half-merged state.
    assert _git(clone, "status", "--porcelain").strip() == ""
    assert "same.txt" in _git(clone, "show", "main:same.txt") or \
           _git(clone, "show", "main:same.txt") == "version A\n"


def test_missing_inputs_fail_cleanly():
    ok, reason = integrate_branch(source_url="", branch="x")
    assert not ok and "source url" in reason
    ok, reason = integrate_branch(source_url="file:///nope", branch="")
    assert not ok
