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
    """Backend returns the TEMPLATE path (with `~` unexpanded). Daemon
    expands against the host's HOME at dispatch time. Critical for the
    docker-backend / host-daemon split — see services.resolve_agent_home."""
    from backend.forge.services import resolve_agent_home

    agent = SimpleNamespace(id="abc123", profile=None)
    home = resolve_agent_home(agent)
    assert home == "~/.agentira/agents/abc123/home"
    assert home.startswith("~"), "home must remain a template"


def test_resolve_agent_home_custom(isolated_home):
    """Explicit home_path on profile wins over the default. Template
    semantics preserved."""
    from backend.forge.services import resolve_agent_home

    prof = SimpleNamespace(home_path="~/code/agents/best")
    agent = SimpleNamespace(id="abc123", profile=prof, profile_id="abc123")
    assert resolve_agent_home(agent) == "~/code/agents/best"


def test_ensure_agent_home_is_template_not_real_path(isolated_home):
    """ensure_agent_home_dir no longer mkdirs (daemon does that on the
    host); it just returns the template. Backend can't safely touch the
    host filesystem from a docker container."""
    from backend.forge.services import ensure_agent_home_dir

    agent = SimpleNamespace(id="xyz789", profile=None)
    home = ensure_agent_home_dir(agent)
    assert home == "~/.agentira/agents/xyz789/home"
    # Backend MUST NOT create the dir — daemon's job
    assert not os.path.isdir(home), "backend created a dir it shouldn't have"


def test_ensure_agent_home_idempotent(isolated_home):
    """Calling twice returns the same template."""
    from backend.forge.services import ensure_agent_home_dir

    agent = SimpleNamespace(id="xyz789", profile=None)
    a = ensure_agent_home_dir(agent)
    b = ensure_agent_home_dir(agent)
    assert a == b
    assert a.startswith("~")


# ── ensure_agent_worktree ────────────────────────────────────────────────


def test_ensure_agent_worktree_returns_template_path(source_repo, isolated_home):
    """Backend returns the TEMPLATE worktree path; daemon does the real
    `git worktree add` on the host. Backend MUST NOT shell out to git
    because the user's repo lives on the host, not in docker."""
    from backend.forge.services import ensure_agent_worktree

    agent = SimpleNamespace(id="a-1", profile=None)
    project = SimpleNamespace(
        id="proj-1", repo_path=str(source_repo), repo_url=None,
    )
    worktree = ensure_agent_worktree(agent, project)
    # Path is templated and lives under the agent's home + repos/<slug>
    assert worktree.startswith("~")
    assert "/repos/" in worktree
    # Daemon's job to actually create it; backend should NOT
    assert not os.path.isdir(os.path.expanduser(worktree)), \
        "backend created the worktree dir — should be daemon-only"


def test_ensure_agent_worktree_idempotent(source_repo, isolated_home):
    from backend.forge.services import ensure_agent_worktree

    agent = SimpleNamespace(id="a-2", profile=None)
    project = SimpleNamespace(
        id="proj-1", repo_path=str(source_repo), repo_url=None,
    )
    w1 = ensure_agent_worktree(agent, project)
    w2 = ensure_agent_worktree(agent, project)
    assert w1 == w2


def test_two_agents_get_separate_worktrees(source_repo, isolated_home):
    """Different agents, same project → different templated paths."""
    from backend.forge.services import ensure_agent_worktree

    a = SimpleNamespace(id="agent-A", profile=None)
    b = SimpleNamespace(id="agent-B", profile=None)
    project = SimpleNamespace(
        id="proj-1", repo_path=str(source_repo), repo_url=None,
    )
    wa = ensure_agent_worktree(a, project)
    wb = ensure_agent_worktree(b, project)
    assert wa != wb
    assert "agent-A" in wa and "agent-B" in wb
