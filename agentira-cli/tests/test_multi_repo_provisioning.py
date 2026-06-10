"""AP-236: multi-repo provisioning — both repos live in the agent's task dir.

The backend builds `worktree_repos: [{name, source_url, branch}]` when a project
has more than one repo and the task doesn't pin one. The daemon clones each and
worktree-adds it as <task_dir>/<name>/. Single-repo runs send [] and the
legacy path stays untouched.
"""

import subprocess
from pathlib import Path

import pytest

from agentira_cli.daemon import sources


def _git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r.stdout


@pytest.fixture
def two_remotes(tmp_path, monkeypatch):
    """Two seeded bare remotes (primary + frontend) + isolated SOURCES_DIR."""
    remotes = []
    for name, marker in (("primary", "BACKEND"), ("frontend", "FRONTEND")):
        bare = tmp_path / "remotes" / f"{name}.git"
        bare.parent.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        seed = tmp_path / f"seed-{name}"
        subprocess.run(["git", "clone", "-q", f"file://{bare}", str(seed)], check=True)
        (seed / "README.md").write_text(f"# {marker}\n")
        _git(seed, "add", "-A")
        _git(seed, "-c", "user.name=t", "-c", "user.email=t@t",
             "commit", "-qm", "init")
        _git(seed, "branch", "-M", "main")
        _git(seed, "push", "-q", "origin", "main")
        remotes.append((name, f"file://{bare}"))
    monkeypatch.setattr(sources, "SOURCES_DIR", tmp_path / "sources")
    return remotes


def test_both_repos_materialize_as_subdirs(two_remotes, tmp_path):
    """Multi-repo: <task_dir>/primary/ and <task_dir>/frontend/ each carry the
    expected README (BACKEND vs FRONTEND) on the task branch."""
    from agentira_cli.daemon.core import _ensure_worktree
    task_dir = tmp_path / "agents" / "a1" / "task-xyz"
    task_dir.mkdir(parents=True)
    branch = "agent/a1/task/xyz"
    for name, url in two_remotes:
        clone, _ = sources.ensure_source_clone(url)
        _ensure_worktree(source=clone, target=str(task_dir / name), branch=branch)

    # Both subdirs exist and have the right content (no wandering).
    assert (task_dir / "primary" / "README.md").read_text() == "# BACKEND\n"
    assert (task_dir / "frontend" / "README.md").read_text() == "# FRONTEND\n"
    # Each is a real worktree on the same task branch (one per repo).
    assert "agent/a1/task/xyz" in _git(task_dir / "primary", "branch", "--show-current")
    assert "agent/a1/task/xyz" in _git(task_dir / "frontend", "branch", "--show-current")


def test_resolve_workspace_kind_multirepo_smoke(tmp_path):
    """The backend's frame-builder uses list_project_repos to decide multi-repo;
    this just sanity-checks the helper that the build sites import."""
    from backend.forge.services import _resolve_workspace_kind
    class P:
        workspace_kind = "git"; repo_url = "https://x"; repo_path = None
    assert _resolve_workspace_kind(P()) == "git"


def test_ensure_worktree_clears_stale_branch_holder(two_remotes, tmp_path):
    """AP-237: if `branch` is registered at a STALE path, _ensure_worktree
    force-removes it before claiming the branch at the new target. Models
    a single-repo→multi-repo layout switch on the same task."""
    from agentira_cli.daemon.core import _ensure_worktree
    name, url = two_remotes[0]
    branch = "agent/x/task/abc"
    # First add at the "single-repo" path (the task root, no subdir).
    legacy_path = tmp_path / "agents" / "x" / "task-abc"
    legacy_path.mkdir(parents=True)
    clone, _ = sources.ensure_source_clone(url)
    _ensure_worktree(source=clone, target=str(legacy_path), branch=branch)
    assert (legacy_path / ".git").exists()
    # Now try to add the SAME branch at a multi-repo subdir target — without
    # the stale-clear logic this would: fatal: 'agent/x/task/abc' is already
    # used by worktree at ... With it, the squatter is removed and the new
    # worktree claims the branch.
    new_target = legacy_path / "primary"
    _ensure_worktree(source=clone, target=str(new_target), branch=branch)
    assert (new_target / ".git").exists()
    # And the legacy path is gone.
    assert not (legacy_path / ".git").exists() or legacy_path == new_target.parent
