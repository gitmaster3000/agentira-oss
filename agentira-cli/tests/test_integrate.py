"""Workflow slice 2 — merging an approved task through its pull request.

Real git repos in tmp (no network): a bare 'remote' standing in for GitHub,
the shared clone via ensure_source_clone (SOURCES_DIR monkeypatched), task
branches made the way the daemon does. GitHub itself is a fake behind the
`github` seam: the daemon must run the project's check on the PR's merge
result first and only then ask GitHub to merge the PR — never `git push`.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agentira_cli.daemon import integrate as integrate_mod
from agentira_cli.daemon import sources
from agentira_cli.daemon.github_pr import GitHubError
from agentira_cli.daemon.integrate import integrate_pull_request


def _git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r.stdout


_ID = ["-c", "user.name=t", "-c", "user.email=t@t"]


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
    _git(seed, *_ID, "commit", "-qm", "init")
    _git(seed, "branch", "-M", "main")
    _git(seed, "push", "-q", "origin", "main")
    monkeypatch.setattr(sources, "SOURCES_DIR", tmp_path / "sources")
    monkeypatch.setattr(integrate_mod, "_sleep", lambda s: None)
    return f"file://{remote}"


def _open_pr(url, number, branch, filename, content="x\n"):
    """Task branch + commit, then what GitHub would publish for the PR:
    refs/pull/<n>/head and the test-merge commit at refs/pull/<n>/merge."""
    clone, _ = sources.ensure_source_clone(url)
    wt = Path(clone).parent / f"wt-{branch.replace('/', '-')}"
    _git(clone, "worktree", "add", "-b", branch, str(wt))
    (wt / filename).parent.mkdir(parents=True, exist_ok=True)
    (wt / filename).write_text(content)
    _git(wt, "add", "-A")
    _git(wt, *_ID, "commit", "-qm", f"work on {branch}")
    head = _git(wt, "rev-parse", "HEAD").strip()
    mwt = Path(clone).parent / f"mwt-{number}"
    _git(clone, "fetch", "-q", "origin")
    _git(clone, "worktree", "add", "--detach", str(mwt), "origin/main")
    _git(mwt, *_ID, "merge", "--no-ff", "-qm", f"merge PR {number}", head)
    merge = _git(mwt, "rev-parse", "HEAD").strip()
    _git(clone, "push", "-q", "origin", f"{head}:refs/pull/{number}/head",
         f"{merge}:refs/pull/{number}/merge")
    _git(clone, "worktree", "remove", "--force", str(mwt))
    return clone, head


def _status(**over):
    base = {"state": "open", "merged": False, "mergeable": True,
            "mergeable_state": "clean", "base_ref": "main", "head_sha": ""}
    base.update(over)
    return base


class FakeGitHub:
    """The GitHub seam: pr_status / merge_pr. Records what the daemon asked."""

    def __init__(self, status, merge_result=(True, "", "merged"), on_merge=None):
        self._status, self._merge_result, self._on_merge = status, merge_result, on_merge
        self.merge_calls, self.status_calls = [], 0

    def pr_status(self, source_url, number):
        self.status_calls += 1
        s = self._status
        return s.pop(0) if isinstance(s, list) and len(s) > 1 else (s[0] if isinstance(s, list) else s)

    def merge_pr(self, source_url, number, *, method, sha):
        if self._on_merge:
            self._on_merge()
        self.merge_calls.append({"number": number, "method": method, "sha": sha})
        return self._merge_result


def _remote_main(clone):
    return _git(clone, "ls-remote", "origin", "main")


def _run(url, gh, **kw):
    kw.setdefault("target_branch", "main")
    return integrate_pull_request(source_url=url, pr_number=kw.pop("pr_number", 1),
                                  github=gh, **kw)


def test_merges_through_the_pr_after_verify_passes(remote_and_sources, tmp_path):
    url = remote_and_sources
    clone, head = _open_pr(url, 1, "agent/a/task/1", "feature.py")
    marker = tmp_path / "verified"
    gh = FakeGitHub(_status(head_sha=head),
                    on_merge=lambda: (_ for _ in ()).throw(AssertionError("merged before verify"))
                    if not marker.exists() else None)
    before = _remote_main(clone)
    ok, reason, verify = _run(url, gh, verify_cmd=f"test -f feature.py && touch {marker}",
                              merge_method="squash")
    assert ok, reason
    assert reason == "merged"
    assert verify["exit_code"] == 0 and not verify["timed_out"]
    assert gh.merge_calls == [{"number": 1, "method": "squash", "sha": head}]
    # The daemon never pushed to the target branch itself.
    assert _remote_main(clone) == before


def test_verify_runs_on_the_prs_merge_result(remote_and_sources):
    """The check sees the merged tree (base + PR), not just the PR branch."""
    url = remote_and_sources
    clone, head = _open_pr(url, 1, "agent/a/task/1", "feature.py")
    gh = FakeGitHub(_status(head_sha=head))
    ok, reason, _ = _run(url, gh, verify_cmd="test -f feature.py && test -f README.md")
    assert ok, reason


def test_verify_failure_does_not_merge(remote_and_sources):
    url = remote_and_sources
    clone, head = _open_pr(url, 1, "agent/a/task/bad", "bad.txt")
    gh = FakeGitHub(_status(head_sha=head))
    ok, reason, verify = _run(url, gh, verify_cmd="echo boom; exit 3")
    assert not ok and reason.startswith("verify_failed")
    assert verify["exit_code"] == 3 and "boom" in verify["log_tail"]
    assert gh.merge_calls == []
    assert "agentira-integrate-" not in _git(clone, "worktree", "list", "--porcelain")


def test_verify_timeout_does_not_merge(remote_and_sources):
    url = remote_and_sources
    _, head = _open_pr(url, 1, "agent/a/task/slow", "slow.txt")
    gh = FakeGitHub(_status(head_sha=head))
    ok, reason, verify = _run(url, gh, verify_cmd="sleep 5", verify_timeout_s=1)
    assert not ok and reason.startswith("verify_timeout")
    assert verify["timed_out"] and verify["exit_code"] is None
    assert gh.merge_calls == []


def test_verify_log_tail_is_bounded(remote_and_sources):
    url = remote_and_sources
    _, head = _open_pr(url, 1, "agent/a/task/loud", "loud.txt")
    gh = FakeGitHub(_status(head_sha=head))
    _, _, verify = _run(url, gh,
                        verify_cmd="for i in $(seq 1 5000); do echo line$i; done; exit 1")
    assert len(verify["log_tail"].splitlines()) <= 200
    assert "line5000" in verify["log_tail"]


def test_no_verify_cmd_merges_without_a_check_result(remote_and_sources):
    url = remote_and_sources
    _, head = _open_pr(url, 1, "agent/a/task/plain", "plain.txt")
    gh = FakeGitHub(_status(head_sha=head))
    ok, _, verify = _run(url, gh)
    assert ok and verify is None
    assert len(gh.merge_calls) == 1


def test_conflicting_pr_is_a_merge_conflict_and_not_merged(remote_and_sources):
    url = remote_and_sources
    gh = FakeGitHub(_status(mergeable=False, mergeable_state="dirty"))
    ok, reason, verify = _run(url, gh, verify_cmd="true")
    assert not ok and reason.startswith("merge_conflict")
    assert verify is None and gh.merge_calls == []


@pytest.mark.parametrize("state", ["blocked", "draft"])
def test_pr_github_says_is_not_mergeable_is_handed_back(remote_and_sources, state):
    url = remote_and_sources
    gh = FakeGitHub(_status(mergeable=True, mergeable_state=state))
    ok, reason, _ = _run(url, gh, verify_cmd="true")
    assert not ok and reason.startswith("pr_not_mergeable")
    assert state in reason
    assert gh.merge_calls == []


def test_waits_while_github_computes_mergeability(remote_and_sources):
    url = remote_and_sources
    _, head = _open_pr(url, 1, "agent/a/task/1", "f.py")
    gh = FakeGitHub([_status(mergeable=None, mergeable_state="unknown", head_sha=head),
                     _status(head_sha=head)])
    ok, reason, _ = _run(url, gh)
    assert ok, reason
    assert gh.status_calls == 2


def test_gives_up_when_github_never_settles(remote_and_sources):
    url = remote_and_sources
    gh = FakeGitHub(_status(mergeable=None, mergeable_state="unknown"))
    ok, reason, _ = _run(url, gh, verify_cmd="true")
    assert not ok and reason.startswith("pr_not_mergeable")
    assert gh.merge_calls == []


def test_github_refusing_the_merge_is_reported_not_swallowed(remote_and_sources):
    url = remote_and_sources
    _, head = _open_pr(url, 1, "agent/a/task/1", "f.py")
    gh = FakeGitHub(_status(head_sha=head),
                    merge_result=(False, "pr_not_mergeable", "Required status check is failing"))
    ok, reason, verify = _run(url, gh, verify_cmd="true")
    assert not ok
    assert reason == "pr_not_mergeable: Required status check is failing"
    assert verify["exit_code"] == 0      # the check did run and pass


def test_head_moved_during_merge_is_reported(remote_and_sources):
    url = remote_and_sources
    _, head = _open_pr(url, 1, "agent/a/task/1", "f.py")
    gh = FakeGitHub(_status(head_sha=head),
                    merge_result=(False, "pr_head_moved", "Head branch was modified"))
    ok, reason, _ = _run(url, gh)
    assert not ok and reason.startswith("pr_head_moved")


def test_stale_merge_result_is_not_verified(remote_and_sources):
    """GitHub's merge ref belongs to a different head than the PR now has."""
    url = remote_and_sources
    _open_pr(url, 1, "agent/a/task/1", "f.py")
    gh = FakeGitHub(_status(head_sha="0" * 40))
    ok, reason, _ = _run(url, gh, verify_cmd="true")
    assert not ok and reason.startswith("pr_head_moved")
    assert gh.merge_calls == []


def test_closed_pr_is_refused(remote_and_sources):
    url = remote_and_sources
    gh = FakeGitHub(_status(state="closed"))
    ok, reason, _ = _run(url, gh)
    assert not ok and reason.startswith("pr_closed")
    assert gh.merge_calls == []


def test_already_merged_pr_counts_as_merged(remote_and_sources):
    url = remote_and_sources
    gh = FakeGitHub(_status(state="closed", merged=True))
    ok, reason, _ = _run(url, gh, verify_cmd="false")
    assert ok and reason == "merged"
    assert gh.merge_calls == []


def test_pr_aimed_at_another_branch_is_refused(remote_and_sources):
    url = remote_and_sources
    gh = FakeGitHub(_status(base_ref="release"))
    ok, reason, _ = _run(url, gh, target_branch="main")
    assert not ok and reason.startswith("pr_base_mismatch")
    assert "release" in reason and "main" in reason
    assert gh.merge_calls == []


def test_refuses_pr_that_committed_injected_files(remote_and_sources):
    url = remote_and_sources
    clone, head = _open_pr(url, 1, "agent/a/task/1", ".agentira/CONVENTIONS.md")
    gh = FakeGitHub(_status(head_sha=head))
    ok, reason, verify = _run(url, gh, verify_cmd="true")
    assert not ok
    assert reason == "injected_files_committed: .agentira/CONVENTIONS.md"
    assert verify is None and gh.merge_calls == []


def test_injected_name_the_target_tracks_is_fine(remote_and_sources, tmp_path):
    """A repo that ships its own CLAUDE.md: editing it is normal work."""
    url = remote_and_sources
    team = tmp_path / "team"
    subprocess.run(["git", "clone", "-q", url, str(team)], check=True)
    (team / "CLAUDE.md").write_text("team rules\n")
    _git(team, "add", "-A")
    _git(team, *_ID, "commit", "-qm", "rules")
    _git(team, "push", "-q", "origin", "main")
    _, head = _open_pr(url, 2, "agent/b/task/2", "CLAUDE.md", "team rules v2\n")
    gh = FakeGitHub(_status(head_sha=head))
    ok, reason, _ = _run(url, gh, pr_number=2)
    assert ok, reason


def test_github_trouble_is_reported_as_unavailable(remote_and_sources):
    url = remote_and_sources
    gh = MagicMock()
    gh.pr_status.side_effect = GitHubError("gh is not installed")
    ok, reason, _ = _run(url, gh)
    assert not ok and reason == "github_unavailable: gh is not installed"


def test_leaves_no_worktrees_or_pr_refs_behind(remote_and_sources):
    url = remote_and_sources
    clone, head = _open_pr(url, 1, "agent/a/task/1", "f.py")
    _run(url, FakeGitHub(_status(head_sha=head)), verify_cmd="true")
    assert "agentira-integrate-" not in _git(clone, "worktree", "list", "--porcelain")
    assert "refs/agentira/pr" not in _git(clone, "for-each-ref")


def test_missing_inputs_fail_cleanly():
    ok, reason, _ = integrate_pull_request(source_url="", pr_number=1, github=MagicMock())
    assert not ok and "source url" in reason
    ok, reason, _ = integrate_pull_request(source_url="file:///nope", pr_number=0,
                                           github=MagicMock())
    assert not ok and "pull request" in reason


# ── daemon frame → integrate_pull_request ──────────────────────────────────

class _SyncThread:
    def __init__(self, target, daemon=None):
        self._t = target

    def start(self):
        self._t()


def _daemon(monkeypatch, merged):
    from agentira_cli.daemon import core
    d = core.AgentiraDaemon.__new__(core.AgentiraDaemon)
    d.client, d._daemon_id = MagicMock(), "d1"
    monkeypatch.setattr(integrate_mod, "integrate_pull_request", merged)
    monkeypatch.setattr(core.threading, "Thread", _SyncThread)
    return d


def test_integrate_frame_without_target_is_refused(monkeypatch):
    merged = MagicMock()
    d = _daemon(monkeypatch, merged)
    d._integrate({"task_id": "t1", "run_id": "r1", "source_url": "file:///x",
                  "pr_number": 7})
    merged.assert_not_called()
    kw = d.client.post_integration_result.call_args.kwargs
    assert kw["ok"] is False and kw["reason"].startswith("target_branch_missing")


def test_integrate_frame_without_pr_number_is_refused(monkeypatch):
    merged = MagicMock()
    d = _daemon(monkeypatch, merged)
    d._integrate({"task_id": "t1", "run_id": "r1", "source_url": "file:///x",
                  "target_branch": "main"})
    merged.assert_not_called()
    kw = d.client.post_integration_result.call_args.kwargs
    assert kw["ok"] is False and kw["reason"].startswith("pr_number_missing")


def test_integrate_frame_passes_pr_verify_and_reports_result(monkeypatch):
    result = {"exit_code": 1, "duration_s": 2.0, "log_tail": "E", "timed_out": False}
    merged = MagicMock(return_value=(False, "verify_failed: exit 1", result))
    d = _daemon(monkeypatch, merged)
    d._integrate({"task_id": "t1", "run_id": "r1", "source_url": "file:///x",
                  "pr_number": 7, "merge_method": "rebase",
                  "target_branch": "main-rsi",
                  "verify_cmd": "scripts/verify.sh", "verify_timeout_s": 600})
    kw = merged.call_args.kwargs
    assert kw["pr_number"] == 7 and kw["merge_method"] == "rebase"
    assert kw["target_branch"] == "main-rsi"
    assert kw["verify_cmd"] == "scripts/verify.sh" and kw["verify_timeout_s"] == 600
    rk = d.client.post_integration_result.call_args.kwargs
    assert rk["ok"] is False and rk["verify"] == result


def test_rest_client_sends_verify_result(monkeypatch):
    from agentira_cli.transport.rest import AgentiraClient as RestClient
    sent = {}
    c = RestClient.__new__(RestClient)
    monkeypatch.setattr(c, "_post", lambda path, body: sent.update(body) or {}, raising=False)
    c.post_integration_result(daemon_id="d", task_id="t", run_id="r", ok=True,
                              reason="merged", verify={"exit_code": 0})
    assert sent["verify"] == {"exit_code": 0}
