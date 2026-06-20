"""AP-296 (T2/T3): the daemon starts every desk from the latest base and
keeps the master copy bare/untouchable.

Drives real git in tmp_path (honest over mocks). Skipped without agentira-cli
or a git binary.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

core = pytest.importorskip(
    "agentira_cli.daemon.core", reason="agentira-cli not installed")
sources = pytest.importorskip(
    "agentira_cli.daemon.sources", reason="agentira-cli not installed")

requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary not on PATH")


def _git(cwd: Path, *args: str) -> str:
    base = ["git", "-c", "user.email=t@t.co", "-c", "user.name=t",
            "-c", "init.defaultBranch=main"]
    r = subprocess.run(base + list(args), cwd=str(cwd), check=True,
                       capture_output=True, text=True)
    return r.stdout.strip()


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A real upstream repo with one commit on main."""
    up = tmp_path / "remote"
    up.mkdir()
    _git(up, "init")
    (up / "f.txt").write_text("v1\n")
    _git(up, "add", ".")
    _git(up, "commit", "-m", "c1")
    return up


@pytest.fixture
def sources_dir(monkeypatch, tmp_path):
    d = tmp_path / "sources"
    monkeypatch.setattr("agentira_cli.daemon.sources.SOURCES_DIR", d)
    monkeypatch.setattr("agentira_cli.daemon.sources.ensure_home", lambda: None)
    return d


@requires_git
def test_clone_is_bare_and_protected(remote, sources_dir):
    clone, reason = sources.ensure_source_clone(str(remote))
    assert reason == "cloned"
    # The master copy is bare → no working tree to sit in or mutate.
    assert sources._is_bare(Path(clone))
    assert not (Path(clone) / "f.txt").exists()


@requires_git
def test_legacy_nonbare_clone_is_reclone_bare(remote, sources_dir):
    # Simulate a pre-existing NON-bare (parked) clone at the slug path.
    dest = sources_dir / sources._slug(str(remote))
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(dest.parent, "clone", str(remote), dest.name)
    assert (dest / ".git").is_dir()        # non-bare
    clone, reason = sources.ensure_source_clone(str(remote))
    assert reason == "cloned"              # re-cloned, not reused
    assert sources._is_bare(Path(clone))


@requires_git
def test_new_desk_starts_from_latest(remote, sources_dir, tmp_path):
    clone, _ = sources.ensure_source_clone(str(remote))
    # Advance upstream AFTER the master was cloned.
    (remote / "f.txt").write_text("v2\n")
    _git(remote, "commit", "-am", "c2")
    sources.ensure_source_clone(str(remote))   # fetch refreshes origin/main

    target = tmp_path / "desk"
    reason = core._ensure_worktree(
        source=clone, target=str(target), branch="agent/x/work",
        base_branch="main", freshness="always_latest")
    assert reason == "ok"
    assert (target / "f.txt").read_text() == "v2\n"   # started current
    behind = _git(target, "rev-list", "--count", "HEAD..origin/main")
    assert behind == "0"


@requires_git
def test_pinned_new_desk_flags_stale(remote, sources_dir, tmp_path):
    clone, _ = sources.ensure_source_clone(str(remote))
    target = tmp_path / "desk"
    reason = core._ensure_worktree(
        source=clone, target=str(target), branch="agent/x/work",
        base_branch="main", freshness="pinned")
    assert reason == "pinned_stale_base"


@requires_git
def test_resume_rebases_onto_latest(remote, sources_dir, tmp_path):
    clone, _ = sources.ensure_source_clone(str(remote))
    target = tmp_path / "desk"
    core._ensure_worktree(source=clone, target=str(target),
                          branch="agent/x/work", base_branch="main",
                          freshness="always_latest")
    # Agent does work on its branch.
    (target / "work.txt").write_text("agent change\n")
    _git(target, "add", ".")
    _git(target, "commit", "-m", "agent work")
    # Upstream advances on a non-conflicting file; refresh the master.
    (remote / "other.txt").write_text("upstream\n")
    _git(remote, "add", ".")
    _git(remote, "commit", "-m", "upstream c2")
    sources.ensure_source_clone(str(remote))
    # Resume: same desk path still exists → reuse + freshen (rebase onto latest).
    reason = core._ensure_worktree(
        source=clone, target=str(target), branch="agent/x/work",
        base_branch="main", freshness="always_latest")
    assert reason == "ok"
    # Agent's work AND the upstream change both present → rebased onto latest.
    assert (target / "work.txt").exists()
    assert (target / "other.txt").read_text() == "upstream\n"
