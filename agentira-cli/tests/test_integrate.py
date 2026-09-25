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
    ok, reason, _ = integrate_branch(source_url=url, branch="agent/a/task/1")
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
    ok, _, _ = integrate_branch(source_url=url, branch="agent/a/task/1")
    assert ok
    _make_task_branch(url, "agent/b/task/2", "b.py")
    ok, reason, _ = integrate_branch(source_url=url, branch="agent/b/task/2")
    assert ok, reason
    tree = _git(clone, "ls-tree", "-r", "--name-only", "main")
    assert "a.py" in tree and "b.py" in tree


def test_conflict_aborts_and_reports(remote_and_sources):
    url = remote_and_sources
    clone = _make_task_branch(url, "agent/a/task/1", "same.txt", "version A\n")
    _make_task_branch(url, "agent/b/task/2", "same.txt", "version B\n")
    ok, _, _ = integrate_branch(source_url=url, branch="agent/a/task/1")
    assert ok
    ok, reason, _ = integrate_branch(source_url=url, branch="agent/b/task/2")
    assert not ok
    assert reason.startswith("merge_conflict")
    # Bare master left clean — no half-merged state, no leftover integrate worktrees.
    assert "MERGE_HEAD" not in _git(clone, "show-ref")
    wt_list = _git(clone, "worktree", "list", "--porcelain")
    assert "agentira-integrate-" not in wt_list
    # First integrate's content still on main (version A).
    assert _git(clone, "show", "main:same.txt") == "version A\n"


def test_missing_inputs_fail_cleanly():
    ok, reason, _ = integrate_branch(source_url="", branch="x")
    assert not ok and "source url" in reason
    ok, reason, _ = integrate_branch(source_url="file:///nope", branch="")
    assert not ok


# ── Loop v1 C5: no silent `main` fallback on the daemon side ──────────────

def test_integrate_frame_without_target_is_refused(monkeypatch):
    from unittest.mock import MagicMock
    from agentira_cli.daemon import core, integrate as integrate_mod
    d = core.AgentiraDaemon.__new__(core.AgentiraDaemon)
    d.client, d._daemon_id = MagicMock(), "d1"
    merged = MagicMock()
    monkeypatch.setattr(integrate_mod, "integrate_branch", merged)

    class _SyncThread:
        def __init__(self, target, daemon=None):
            self._t = target

        def start(self):
            self._t()
    monkeypatch.setattr(core.threading, "Thread", _SyncThread)

    d._integrate({"task_id": "t1", "run_id": "r1", "source_url": "file:///x",
                  "branch": "agent/t1"})
    merged.assert_not_called()
    kw = d.client.post_integration_result.call_args.kwargs
    assert kw["ok"] is False and kw["reason"].startswith("target_branch_missing")


# ── Loop v1 C6: merge → run the project's verify command → push on pass ──

def _remote_main_files(clone):
    _git(clone, "fetch", "-q", "origin")
    return _git(clone, "ls-tree", "-r", "--name-only", "origin/main")


def test_verify_pass_pushes(remote_and_sources):
    url = remote_and_sources
    clone = _make_task_branch(url, "agent/a/task/ok", "ok.txt")
    ok, reason, verify = integrate_branch(
        source_url=url, branch="agent/a/task/ok", target_branch="main",
        verify_cmd="test -f ok.txt")
    assert ok, reason
    assert verify["exit_code"] == 0 and not verify["timed_out"]
    assert "ok.txt" in _remote_main_files(clone)


def test_verify_fail_does_not_push(remote_and_sources):
    url = remote_and_sources
    clone = _make_task_branch(url, "agent/a/task/bad", "bad.txt")
    ok, reason, verify = integrate_branch(
        source_url=url, branch="agent/a/task/bad", target_branch="main",
        verify_cmd="echo boom; exit 3")
    assert not ok and reason.startswith("verify_failed")
    assert verify["exit_code"] == 3 and "boom" in verify["log_tail"]
    assert "bad.txt" not in _remote_main_files(clone)
    assert "bad.txt" not in _git(clone, "ls-tree", "-r", "--name-only", "main")
    assert "agentira-integrate-" not in _git(clone, "worktree", "list", "--porcelain")


def test_verify_timeout_does_not_push(remote_and_sources):
    url = remote_and_sources
    clone = _make_task_branch(url, "agent/a/task/slow", "slow.txt")
    ok, reason, verify = integrate_branch(
        source_url=url, branch="agent/a/task/slow", target_branch="main",
        verify_cmd="sleep 5", verify_timeout_s=1)
    assert not ok and reason.startswith("verify_timeout")
    assert verify["timed_out"] and verify["exit_code"] is None
    assert "slow.txt" not in _remote_main_files(clone)


def test_verify_log_tail_is_bounded(remote_and_sources):
    url = remote_and_sources
    _make_task_branch(url, "agent/a/task/loud", "loud.txt")
    _, _, verify = integrate_branch(
        source_url=url, branch="agent/a/task/loud", target_branch="main",
        verify_cmd="for i in $(seq 1 5000); do echo line$i; done; exit 1")
    assert len(verify["log_tail"].splitlines()) <= 200
    assert "line5000" in verify["log_tail"]


def test_no_verify_cmd_reports_no_verify_result(remote_and_sources):
    url = remote_and_sources
    _make_task_branch(url, "agent/a/task/plain", "plain.txt")
    ok, _, verify = integrate_branch(source_url=url, branch="agent/a/task/plain")
    assert ok and verify is None


def test_integrate_frame_passes_verify_and_reports_it(monkeypatch):
    from unittest.mock import MagicMock
    from agentira_cli.daemon import core, integrate as integrate_mod
    d = core.AgentiraDaemon.__new__(core.AgentiraDaemon)
    d.client, d._daemon_id = MagicMock(), "d1"
    result = {"exit_code": 1, "duration_s": 2.0, "log_tail": "E", "timed_out": False}
    merged = MagicMock(return_value=(False, "verify_failed: exit 1", result))
    monkeypatch.setattr(integrate_mod, "integrate_branch", merged)

    class _SyncThread:
        def __init__(self, target, daemon=None):
            self._t = target

        def start(self):
            self._t()
    monkeypatch.setattr(core.threading, "Thread", _SyncThread)

    d._integrate({"task_id": "t1", "run_id": "r1", "source_url": "file:///x",
                  "branch": "agent/t1", "target_branch": "main-rsi",
                  "verify_cmd": "scripts/verify.sh", "verify_timeout_s": 600})
    assert merged.call_args.kwargs["verify_cmd"] == "scripts/verify.sh"
    assert merged.call_args.kwargs["verify_timeout_s"] == 600
    kw = d.client.post_integration_result.call_args.kwargs
    assert kw["ok"] is False and kw["verify"] == result


def test_rest_client_sends_verify_result(monkeypatch):
    from agentira_cli.transport.rest import AgentiraClient as RestClient
    sent = {}
    c = RestClient.__new__(RestClient)
    monkeypatch.setattr(c, "_post", lambda path, body: sent.update(body) or {}, raising=False)
    c.post_integration_result(daemon_id="d", task_id="t", run_id="r", ok=True,
                              reason="merged", verify={"exit_code": 0})
    assert sent["verify"] == {"exit_code": 0}
