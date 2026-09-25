"""Injected agent files (.agentira/CONVENTIONS.md + courtesy links) must never
enter an agent's commit, whatever the project — the materializer lists what it
created in the worktree's git exclude file (linked-worktree safe)."""

import subprocess
from pathlib import Path

import pytest

from agentira_cli.daemon import materializer

INJECTED = [materializer.CONVENTIONS_REL, *materializer.COURTESY_NAMES]


def _git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r.stdout


def _commit_all(cwd, msg="agent work"):
    _git(cwd, "add", "-A")
    _git(cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)
    return _git(cwd, "show", "--name-only", "--format=", "HEAD").split()


@pytest.fixture(autouse=True)
def _scratch_workdir(tmp_path, monkeypatch):
    monkeypatch.setattr(materializer, "task_workdir",
                        lambda *_: tmp_path / "scratch")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / "README.md").write_text("# app\n")
    _commit_all(r, "init")
    return r


def _materialize(path):
    return materializer.materialize(workspace_id="w", task_id="t",
                                    repo_path=str(path), conventions_md="rules")


def test_injected_files_stay_out_of_commit(repo):
    _materialize(repo)
    (repo / "feature.py").write_text("x = 1\n")
    committed = _commit_all(repo)
    assert committed == ["feature.py"]
    for p in INJECTED:
        assert (repo / p).exists()


def test_linked_worktree_excludes_injected_files(repo, tmp_path):
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "agent/task", str(wt))
    _materialize(wt)
    (wt / "feature.py").write_text("x = 1\n")
    assert _commit_all(wt) == ["feature.py"]


def test_exclude_is_idempotent(repo):
    _materialize(repo)
    _materialize(repo)
    exclude = Path(repo / ".git/info/exclude").read_text().splitlines()
    for p in INJECTED:
        assert exclude.count(f"/{p}") == 1


def test_repo_tracked_claude_md_untouched_and_not_excluded(repo):
    (repo / "CLAUDE.md").write_text("team rules\n")
    _commit_all(repo, "add CLAUDE.md")
    _materialize(repo)
    exclude = Path(repo / ".git/info/exclude").read_text().splitlines()
    assert "/CLAUDE.md" not in exclude
    assert not (repo / "CLAUDE.md").is_symlink()
    assert (repo / "CLAUDE.md").read_text() == "team rules\n"
    # Edits to the repo's own CLAUDE.md still get committed.
    (repo / "CLAUDE.md").write_text("team rules v2\n")
    assert _commit_all(repo) == ["CLAUDE.md"]


def test_non_git_dir_is_fine(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    _materialize(d)
    assert (d / materializer.CONVENTIONS_REL).read_text() == "rules"
