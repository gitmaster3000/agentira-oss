"""The real GitHub seam: `gh api` under the user's own login (the same
ambient credentials `git push` used to rely on)."""

import json
import subprocess
from unittest.mock import MagicMock

import pytest

from agentira_cli.daemon import github_pr
from agentira_cli.daemon.github_pr import GitHubError, GhCli, repo_slug


@pytest.mark.parametrize("url,slug", [
    ("https://github.com/o/r", "o/r"),
    ("https://github.com/o/r.git", "o/r"),
    ("https://user:tok@github.com/o/r.git", "o/r"),
    ("git@github.com:o/r.git", "o/r"),
    ("ssh://git@github.com/o/r.git", "o/r"),
])
def test_repo_slug_parses_github_remotes(url, slug):
    assert repo_slug(url) == slug


def test_repo_slug_rejects_other_hosts():
    with pytest.raises(GitHubError, match="GitHub"):
        repo_slug("https://gitlab.com/o/r.git")


def _proc(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


def test_pr_status_maps_the_api_fields(monkeypatch):
    body = {"state": "open", "merged": False, "mergeable": True,
            "mergeable_state": "clean", "base": {"ref": "main"},
            "head": {"sha": "abc"}}
    run = MagicMock(return_value=_proc(json.dumps(body)))
    monkeypatch.setattr(github_pr.subprocess, "run", run)
    s = GhCli().pr_status("https://github.com/o/r.git", 5)
    assert s == {"state": "open", "merged": False, "mergeable": True,
                 "mergeable_state": "clean", "base_ref": "main", "head_sha": "abc"}
    assert run.call_args.args[0][:3] == ["gh", "api", "repos/o/r/pulls/5"]


def test_merge_pr_sends_method_and_head_sha(monkeypatch):
    run = MagicMock(return_value=_proc("{}"))
    monkeypatch.setattr(github_pr.subprocess, "run", run)
    assert GhCli().merge_pr("https://github.com/o/r", 5, method="squash", sha="abc") \
        == (True, "", "merged")
    cmd = run.call_args.args[0]
    assert "PUT" in cmd and "repos/o/r/pulls/5/merge" in cmd
    assert "merge_method=squash" in cmd and "sha=abc" in cmd


@pytest.mark.parametrize("code,kind", [(405, "pr_not_mergeable"), (409, "pr_head_moved")])
def test_merge_pr_classifies_refusals(monkeypatch, code, kind):
    err = json.dumps({"message": "nope"}) + f"\ngh: nope (HTTP {code})"
    monkeypatch.setattr(github_pr.subprocess, "run",
                        MagicMock(return_value=_proc(err, err, 1)))
    ok, got, msg = GhCli().merge_pr("https://github.com/o/r", 5, method="merge", sha="a")
    assert not ok and got == kind and "nope" in msg


def test_missing_gh_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(github_pr.subprocess, "run",
                        MagicMock(side_effect=FileNotFoundError()))
    with pytest.raises(GitHubError, match="gh"):
        GhCli().pr_status("https://github.com/o/r", 5)
