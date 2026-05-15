"""Tests for the per-agent home + worktree primitives.

These exercise resolve_agent_home / ensure_agent_home_dir /
ensure_worktree_base / ensure_agent_worktree without going through the
daemon dispatch path. We need real git here (it's a thin shell around
subprocess), so the tests create a real source repo in tmp_path and
verify worktree creation."""

from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest


# Skip the whole module if git isn't on PATH — we don't try to mock the
# subprocess shells because that would test our mocks, not git behavior.
pytest.importorskip("sqlalchemy")
if not subprocess.run(["which", "git"], capture_output=True).stdout.strip():
    pytest.skip("git not installed", allow_module_level=True)


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    """Redirect ~/.agentira/agents/... resolution into tmp_path."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home


@pytest.fixture()
def source_repo(tmp_path):
    """A real git repo with one initial commit. Acts as project.repo_path."""
    repo = tmp_path / "user-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


# ── resolve_agent_home / ensure_agent_home_dir ───────────────────────────


def test_resolve_agent_home_default(isolated_home):
    from backend.forge.services import resolve_agent_home

    agent = SimpleNamespace(id="abc123", profile=None)
    home = resolve_agent_home(agent)
    assert home == str(isolated_home / ".agentira/agents/abc123/home")


def test_resolve_agent_home_custom(isolated_home):
    """Explicit home_path on profile wins over the default."""
    from backend.forge.services import resolve_agent_home

    prof = SimpleNamespace(home_path="~/code/agents/best")
    agent = SimpleNamespace(id="abc123", profile=prof, profile_id="abc123")
    assert resolve_agent_home(agent) == str(isolated_home / "code/agents/best")


def test_ensure_agent_home_creates_subdirs(isolated_home):
    from backend.forge.services import ensure_agent_home_dir

    agent = SimpleNamespace(id="xyz789", profile=None)
    home = ensure_agent_home_dir(agent)
    assert os.path.isdir(home)
    for sub in ("repos", "memory", "notes", ".agentira"):
        assert os.path.isdir(os.path.join(home, sub)), f"missing {sub}"


def test_ensure_agent_home_idempotent(isolated_home):
    from backend.forge.services import ensure_agent_home_dir

    agent = SimpleNamespace(id="xyz789", profile=None)
    ensure_agent_home_dir(agent)
    # Drop a sentinel into a subdir and re-run — it shouldn't be wiped
    sentinel = os.path.join(
        isolated_home, ".agentira/agents/xyz789/home/notes/keep.txt",
    )
    open(sentinel, "w").write("preserved")
    ensure_agent_home_dir(agent)
    assert open(sentinel).read() == "preserved"


# ── ensure_worktree_base ─────────────────────────────────────────────────


def test_ensure_worktree_base_uses_local_path(source_repo):
    from backend.forge.services import ensure_worktree_base

    project = SimpleNamespace(
        id="proj-1", repo_path=str(source_repo), repo_url=None,
    )
    base = ensure_worktree_base(project)
    assert base == str(source_repo)


def test_ensure_worktree_base_raises_when_no_source(tmp_path, isolated_home):
    from backend.forge.services import ensure_worktree_base

    project = SimpleNamespace(
        id="proj-empty",
        repo_path=str(tmp_path / "does-not-exist"),
        repo_url=None,
    )
    with pytest.raises(ValueError, match="no usable git source"):
        ensure_worktree_base(project)


def test_ensure_worktree_base_clones_from_repo_url(source_repo, isolated_home):
    """Local path missing but repo_url set → clone into cache."""
    from backend.forge.services import ensure_worktree_base

    project = SimpleNamespace(
        id="proj-cloud",
        repo_path="/path/that/does/not/exist",
        repo_url=str(source_repo),  # any URL git can clone — local path works
    )
    base = ensure_worktree_base(project)
    assert os.path.isdir(os.path.join(base, ".git"))
    # Second call is idempotent (no re-clone)
    base2 = ensure_worktree_base(project)
    assert base == base2


# ── ensure_agent_worktree ────────────────────────────────────────────────


def test_ensure_agent_worktree_creates_worktree(source_repo, isolated_home):
    from backend.forge.services import ensure_agent_worktree

    agent = SimpleNamespace(id="a-1", profile=None)
    project = SimpleNamespace(
        id="proj-1", repo_path=str(source_repo), repo_url=None,
    )
    worktree = ensure_agent_worktree(agent, project)
    assert os.path.isdir(worktree)
    # Worktree marker (file or dir at .git)
    git_marker = os.path.join(worktree, ".git")
    assert os.path.exists(git_marker)


def test_ensure_agent_worktree_idempotent(source_repo, isolated_home):
    from backend.forge.services import ensure_agent_worktree

    agent = SimpleNamespace(id="a-2", profile=None)
    project = SimpleNamespace(
        id="proj-1", repo_path=str(source_repo), repo_url=None,
    )
    w1 = ensure_agent_worktree(agent, project)
    w2 = ensure_agent_worktree(agent, project)
    assert w1 == w2
    # On-disk it should still be a single working tree
    output = subprocess.run(
        ["git", "-C", str(source_repo), "worktree", "list"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert w1 in output


def test_two_agents_get_separate_worktrees(source_repo, isolated_home):
    """Different agents, same project → different worktrees, both work."""
    from backend.forge.services import ensure_agent_worktree

    a = SimpleNamespace(id="agent-A", profile=None)
    b = SimpleNamespace(id="agent-B", profile=None)
    project = SimpleNamespace(
        id="proj-1", repo_path=str(source_repo), repo_url=None,
    )
    wa = ensure_agent_worktree(a, project)
    wb = ensure_agent_worktree(b, project)
    assert wa != wb
    assert os.path.isdir(wa) and os.path.isdir(wb)
