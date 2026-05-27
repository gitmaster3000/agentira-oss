"""diff_capture work-signal facts + untracked surfacing (ADR 009 / AP-136).

Guards that:
- new untracked files the agent forgot to `git add` are surfaced (never lost)
  and set the `untracked` fact,
- the materializer's own .agentira/* (and courtesy CLAUDE.md etc.) never count
  as the agent's work,
- tracked edits set `tracked`, a clean tree sets nothing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentira_cli.daemon import diff_capture


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("ignored/\n*.log\n")
    (tmp_path / "tracked.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_clean_tree_no_work(repo):
    _stat, _diff, facts = diff_capture.capture_with_signal(repo)
    assert facts == {"tracked": False, "untracked": False, "committed": False}


def test_tracked_edit_sets_tracked(repo):
    (repo / "tracked.py").write_text("x = 2\n")
    stat, diff, facts = diff_capture.capture_with_signal(repo)
    assert facts["tracked"] is True
    assert "tracked.py" in diff


def test_new_untracked_file_is_surfaced_and_flagged(repo):
    (repo / "newfile.py").write_text("print('hi')\n")
    stat, diff, facts = diff_capture.capture_with_signal(repo)
    assert facts["untracked"] is True
    assert "newfile.py" in diff  # surfaced — never silently lost
    assert "untracked" in stat.lower()


def test_gitignored_and_agentira_do_not_count(repo):
    (repo / "debug.log").write_text("noise\n")          # gitignored
    (repo / ".agentira").mkdir()
    (repo / ".agentira" / "CONVENTIONS.md").write_text("conv\n")  # materializer
    (repo / "CLAUDE.md").symlink_to(".agentira/CONVENTIONS.md")   # courtesy
    _stat, diff, facts = diff_capture.capture_with_signal(repo)
    assert facts == {"tracked": False, "untracked": False, "committed": False}
    assert "debug.log" not in diff
    assert ".agentira" not in diff


def test_capture_backcompat_two_tuple(repo):
    (repo / "tracked.py").write_text("x = 9\n")
    result = diff_capture.capture(repo)
    assert isinstance(result, tuple) and len(result) == 2
