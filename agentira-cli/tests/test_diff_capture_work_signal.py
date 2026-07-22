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


_ALL_FALSE = {"tracked": False, "untracked": False, "committed": False,
              "lines_changed": 0, "files_changed": 0, "untracked_count": 0}


def test_clean_tree_no_work(repo):
    _stat, _diff, facts = diff_capture.capture_with_signal(repo)
    assert facts == _ALL_FALSE


def test_tracked_edit_sets_tracked(repo):
    (repo / "tracked.py").write_text("x = 2\n")
    stat, diff, facts = diff_capture.capture_with_signal(repo)
    assert facts["tracked"] is True
    assert "tracked.py" in diff
    # AP-149 diagnostic counts
    assert facts["lines_changed"] >= 2  # at least the +1/-1 of the edit
    assert facts["files_changed"] == 1


def test_new_untracked_file_is_surfaced_and_flagged(repo):
    (repo / "newfile.py").write_text("print('hi')\n")
    stat, diff, facts = diff_capture.capture_with_signal(repo)
    assert facts["untracked"] is True
    assert facts["untracked_count"] == 1
    assert "newfile.py" in diff  # surfaced — never silently lost
    assert "untracked" in stat.lower()


def test_gitignored_and_agentira_do_not_count(repo):
    (repo / "debug.log").write_text("noise\n")          # gitignored
    (repo / ".agentira").mkdir()
    (repo / ".agentira" / "CONVENTIONS.md").write_text("conv\n")  # materializer
    (repo / "CLAUDE.md").symlink_to(".agentira/CONVENTIONS.md")   # courtesy
    _stat, diff, facts = diff_capture.capture_with_signal(repo)
    assert facts == _ALL_FALSE
    assert "debug.log" not in diff
    assert ".agentira" not in diff


def test_capture_backcompat_two_tuple(repo):
    (repo / "tracked.py").write_text("x = 9\n")
    result = diff_capture.capture(repo)
    assert isinstance(result, tuple) and len(result) == 2


# ── AP-149 ────────────────────────────────────────────────────────────────

def test_tracked_materializer_file_is_excluded_from_tracked_diff(repo):
    """If `.agentira/CONVENTIONS.md` ended up tracked (legacy commit, user
    error), a rewrite by the materializer must not crystallize a run."""
    (repo / ".agentira").mkdir(exist_ok=True)
    conv = repo / ".agentira" / "CONVENTIONS.md"
    conv.write_text("old\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "track materializer file")
    # Materializer-style rewrite (different content)
    conv.write_text("new conventions for this run\n")
    _stat, diff, facts = diff_capture.capture_with_signal(repo)
    assert facts["tracked"] is False
    assert facts["lines_changed"] == 0
    assert facts["files_changed"] == 0
    assert "CONVENTIONS.md" not in diff


def test_scratch_dirs_are_excluded_from_untracked(repo):
    """A new project without .gitignore must not crystallize from npm /
    pip / build side-effects."""
    (repo / "node_modules" / "foo").mkdir(parents=True)
    (repo / "node_modules" / "foo" / "index.js").write_text("// noise\n")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "bar.cpython-311.pyc").write_text("noise\n")
    (repo / ".venv" / "lib").mkdir(parents=True)
    (repo / ".venv" / "lib" / "baz.py").write_text("# noise\n")
    (repo / "dist").mkdir()
    (repo / "dist" / "out.js").write_text("// bundled\n")
    _stat, diff, facts = diff_capture.capture_with_signal(repo)
    assert facts["untracked"] is False
    assert facts["untracked_count"] == 0
    assert facts == _ALL_FALSE
    assert "node_modules" not in diff
    assert "__pycache__" not in diff
    assert ".venv" not in diff
    assert "dist" not in diff


def test_real_file_alongside_scratch_still_counts(repo):
    """Scratch is excluded but a real new file still surfaces."""
    (repo / "node_modules" / "left").mkdir(parents=True)
    (repo / "node_modules" / "left" / "pad.js").write_text("noise\n")
    (repo / "src").mkdir()
    (repo / "src" / "handler.py").write_text("def handle(): pass\n")
    _stat, diff, facts = diff_capture.capture_with_signal(repo)
    assert facts["untracked"] is True
    assert facts["untracked_count"] == 1
    assert "src/handler.py" in diff
    assert "node_modules" not in diff


def test_lines_changed_is_accurate(repo):
    """+3 / -1 → lines_changed == 4."""
    (repo / "tracked.py").write_text("a = 1\nb = 2\nc = 3\nd = 4\n")  # +3, -1
    _stat, _diff, facts = diff_capture.capture_with_signal(repo)
    assert facts["files_changed"] == 1
    # Exact: `tracked.py` was `x = 1\n` (1 line) → now 4 lines → +4 / -1 = 5
    assert facts["lines_changed"] == 5


def test_os_detritus_is_excluded(repo):
    """`.DS_Store` (macOS) must not crystallize a run."""
    (repo / ".DS_Store").write_text("\0")
    _stat, _diff, facts = diff_capture.capture_with_signal(repo)
    assert facts == _ALL_FALSE


def test_count_diff_lines_skips_headers_and_untracked_listing():
    """Direct unit test for the line counter — guards against the appended
    untracked-files section double-counting (lines start with `  + `, not
    `+`, so they must be ignored by startswith('+'))."""
    body = (
        "diff --git a/x b/x\n"
        "index 0..1 100644\n"
        "--- a/x\n"
        "+++ b/x\n"
        "@@ -1,2 +1,3 @@\n"
        "-old\n"
        "+new1\n"
        "+new2\n"
        "\n"
        "# New untracked files (not yet committed):\n"
        "  + src/foo.py\n"
        "  + src/bar.py\n"
    )
    assert diff_capture._count_diff_lines(body) == 3  # -old, +new1, +new2
