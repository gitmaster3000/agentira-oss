"""AP-197 / AP-196: daemon-owned git-workspace source clones.

Pure unit tests — NO real network. `subprocess.run` and `SOURCES_DIR` are
monkeypatched so the clone/fetch paths exercise the real control flow against
a tmp dir and a fake git. Mirrors the style of `test_ensure_worktree.py`.
"""

from __future__ import annotations

import subprocess

import pytest

from agentira_cli.daemon import sources
from agentira_cli.daemon.sources import (
    SourceProvisionError,
    _slug,
    classify_provision_error,
    ensure_source_clone,
)


# ── _slug: same repo across URL forms collapses to ONE dir name ──────────

def test_slug_collapses_url_forms():
    https = _slug("https://github.com/o/r")
    dotgit = _slug("https://github.com/o/r.git")
    ssh = _slug("git@github.com:o/r.git")
    assert https == dotgit == ssh
    # And it's a single, filesystem-safe path segment.
    assert https
    assert "/" not in https
    assert all(c.isalnum() or c in "._-" for c in https)


def test_slug_filesystem_safe_for_messy_url():
    s = _slug("https://user:tok@example.com:8080/Org/My Repo!.git")
    assert "/" not in s
    assert ":" not in s
    assert " " not in s
    assert all(c.isalnum() or c in "._-" for c in s)


def test_slug_empty_falls_back():
    assert _slug("") == "repo"


# ── classify_provision_error: raw error → human cause ────────────────────

def test_classify_tcc_under_protected_folder():
    # exit 128 while the source lives under a TCC-protected folder.
    msg = classify_provision_error(
        Exception("git worktree add failed: exit status 128"),
        source="/Users/x/Desktop/proj",
    )
    assert "TCC" in msg


def test_classify_tcc_operation_not_permitted():
    msg = classify_provision_error(Exception("Operation not permitted"))
    assert "TCC" in msg


def test_classify_authentication():
    msg = classify_provision_error(
        Exception("fatal: Authentication failed for 'https://github.com/o/r'")
    )
    assert "authentication" in msg.lower()


def test_classify_not_a_repo():
    msg = classify_provision_error(
        Exception("fatal: not a git repository (or any parent)")
    )
    assert "not a usable git repository" in msg


def test_classify_generic_fallback():
    msg = classify_provision_error(Exception("disk full"))
    assert "provisioning failed" in msg.lower()
    assert "TCC" not in msg
    assert "authentication" not in msg.lower()


# ── ensure_source_clone ──────────────────────────────────────────────────

def test_ensure_source_clone_empty_url_raises():
    with pytest.raises(SourceProvisionError):
        ensure_source_clone("")
    with pytest.raises(SourceProvisionError):
        ensure_source_clone("   ")


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def sources_dir(tmp_path, monkeypatch):
    """Point SOURCES_DIR at a tmp dir for both `sources` and its `paths`
    import so neither a real clone nor a real ~/.agentira is touched."""
    d = tmp_path / "sources"
    monkeypatch.setattr(sources, "SOURCES_DIR", d)
    # ensure_home() must not create the real ~/.agentira either.
    monkeypatch.setattr(sources, "ensure_home", lambda: tmp_path)
    return d


def _is_bare_check(cmd) -> bool:
    return "rev-parse" in cmd and "--is-bare-repository" in cmd


def test_fresh_dir_triggers_clone(sources_dir, monkeypatch):
    # Fresh source: no dir yet, so `git clone --bare` runs, followed by the
    # remote-tracking config + fetch that make origin/<base> resolvable for
    # the per-task worktrees. Returns reason "cloned".
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        return _FakeCompleted(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    path, reason = ensure_source_clone("https://github.com/o/r.git")
    assert reason == "cloned"
    assert path.endswith(_slug("https://github.com/o/r.git"))
    # First git op is the bare clone; a fetch follows so origin/* is populated.
    assert calls[0][:3] == ["git", "clone", "--bare"]
    assert any("fetch" in c for c in calls)


def test_existing_clone_triggers_fetch(sources_dir, monkeypatch):
    # Pre-create a cached bare clone dir; `_is_bare` must report bare so we
    # take the refresh path (`git fetch --prune`) rather than re-cloning.
    dest = sources_dir / _slug("https://github.com/o/r")
    dest.mkdir(parents=True)

    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if _is_bare_check(cmd):
            return _FakeCompleted(returncode=0, stdout="true")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    path, reason = ensure_source_clone("https://github.com/o/r")
    assert reason == "ok"
    assert path == str(dest)
    # No re-clone; the only network op is the fetch.
    assert not any(c[:3] == ["git", "clone", "--bare"] for c in calls)
    assert any("fetch" in c for c in calls)


def test_clone_nonzero_raises_and_cleans_up(sources_dir, monkeypatch):
    def fake_run(cmd, *a, **k):
        # Simulate a partial clone dir left behind by a failed `git clone`.
        dest = cmd[-1]
        import os
        os.makedirs(dest, exist_ok=True)
        return _FakeCompleted(returncode=128, stderr="fatal: repository not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SourceProvisionError) as ei:
        ensure_source_clone("https://github.com/o/missing.git")
    assert "missing" in str(ei.value) or "repository not found" in str(ei.value)
    # Partial clone must have been cleaned up.
    dest = sources_dir / _slug("https://github.com/o/missing.git")
    assert not dest.exists()


def test_fetch_failure_is_nonfatal(sources_dir, monkeypatch):
    """A failed `git fetch` on a cached bare clone is best-effort: still ok.
    The is-bare probe must succeed so we stay on the refresh path; only the
    fetch fails."""
    dest = sources_dir / _slug("https://github.com/o/r")
    dest.mkdir(parents=True)

    def fake_run(cmd, *a, **k):
        if _is_bare_check(cmd):
            return _FakeCompleted(returncode=0, stdout="true")
        return _FakeCompleted(returncode=1, stderr="network down")

    monkeypatch.setattr(subprocess, "run", fake_run)

    path, reason = ensure_source_clone("https://github.com/o/r")
    assert reason == "ok"
    assert path == str(dest)
