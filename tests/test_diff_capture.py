"""Tests for daemon-side diff capture (AP-54, Phase F).

Skipped when agentira-cli isn't installed (CI's backend-only unit job).

We avoid mocking subprocess and instead drive real git in tmp_path —
git is on the CI runner anyway, and the integration coverage is more
honest than a mock-heavy test would be.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

agentira_cli_diff = pytest.importorskip(
    "agentira_cli.daemon.diff_capture",
    reason="agentira-cli package not installed",
)
capture = agentira_cli_diff.capture
MAX_DIFF_BYTES = agentira_cli_diff.MAX_DIFF_BYTES

# Tests that drive a real `git` binary are skipped on hosts without it
# (some minimal containers). The pure-Python paths (None / nonexistent /
# non-repo) still run everywhere.
requires_git = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git binary not on PATH",
)


def _git(cwd: Path, *args: str) -> None:
    """Invoke git with sensible defaults so tests don't fail on missing
    user.name / user.email or default-branch policy."""
    base = ["git", "-c", "user.email=test@example.com",
            "-c", "user.name=Test", "-c", "init.defaultBranch=main"]
    subprocess.run(base + list(args), cwd=str(cwd), check=True,
                   capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo with one committed file — fixture for diff tests."""
    _git(tmp_path, "init")
    (tmp_path / "README.md").write_text("# original\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    return tmp_path


def test_capture_returns_empty_for_non_repo(tmp_path: Path):
    diff_stat, diff = capture(tmp_path)
    assert diff_stat == ""
    assert diff == ""


@requires_git
def test_capture_returns_empty_for_clean_repo(repo: Path):
    """No uncommitted changes → empty diff."""
    diff_stat, diff = capture(repo)
    assert diff_stat == ""
    assert diff == ""


@requires_git
def test_capture_returns_diff_for_modified_file(repo: Path):
    (repo / "README.md").write_text("# modified\n")
    diff_stat, diff = capture(repo)
    assert "README.md" in diff_stat
    assert "-# original" in diff
    assert "+# modified" in diff


@requires_git
def test_capture_handles_new_files(repo: Path):
    """ADR 009 / AP-149: capture ALSO surfaces NEW untracked files (plain
    `git diff` would miss them, since it diffs vs HEAD). The earlier baseline
    expected empty here; scope expanded to report untracked, so this asserts
    the file is now surfaced."""
    (repo / "newfile.txt").write_text("hello\n")
    diff_stat, diff = capture(repo)
    assert "newfile.txt" in diff


@requires_git
def test_capture_caps_oversized_diff(repo: Path):
    """A massive change is trimmed to MAX_DIFF_BYTES + a notice."""
    big = "x" * (MAX_DIFF_BYTES + 5_000) + "\n"
    (repo / "README.md").write_text(big)
    _, diff = capture(repo)
    # Trimmed: encoded length is bounded by MAX_DIFF_BYTES + the notice.
    assert "[diff truncated" in diff
    body_only = diff.split("[diff truncated")[0]
    assert len(body_only.encode("utf-8")) <= MAX_DIFF_BYTES + 100  # tolerate overhead


def test_capture_returns_empty_for_none_workdir():
    diff_stat, diff = capture(None)
    assert diff_stat == ""
    assert diff == ""


def test_capture_returns_empty_for_nonexistent_path():
    diff_stat, diff = capture("/nonexistent/path/xyz")
    assert diff_stat == ""
    assert diff == ""


@requires_git
def test_capture_handles_nested_workdir(repo: Path):
    """If workdir is a subdir of the repo, git still finds the toplevel
    and reports the diff correctly."""
    sub = repo / "src"
    sub.mkdir()
    (repo / "README.md").write_text("# nested-test\n")
    diff_stat, diff = capture(sub)
    assert "README.md" in diff_stat
