"""Branch integration — merge an approved task through its pull request.

When a reviewer's run succeeds, the backend workflow driver sends an
`integrate` frame naming the task's pull request. Nothing is merged without
a PR, and nothing is pushed by this module: it proves the PR's merge result
works, then asks GitHub to merge the PR.

  1. read the PR's state from GitHub (open? aimed at the right branch?
     mergeable?);
  2. fetch GitHub's own test-merge of the PR (`refs/pull/N/merge`) into the
     shared bare clone (`~/.agentira/sources/<slug>`) and run the project's
     verify command on it in a short-lived worktree;
  3. only if that passed, merge the PR through the GitHub API, pinned to the
     head that was checked.

This is CODE doing a deterministic action with integrity guarantees (the
config decides *whether/where/how* to integrate; this module decides
*nothing*):
- per-clone locking (no two integrations race the same repo);
- every failure → worktree + temp refs cleaned up, classified reason
  ("merge_conflict", "verify_failed", "pr_not_mergeable", …).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from agentira_cli.daemon.github_pr import GhCli, GitHubError
from agentira_cli.daemon.materializer import CONVENTIONS_REL, COURTESY_NAMES
from agentira_cli.daemon.sources import (
    _lock_for,
    _git_env,
    ensure_source_clone,
)

logger = logging.getLogger("agentira.daemon.integrate")

_GIT_TIMEOUT = 120


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", cwd, *args],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT, env=_git_env(),
    )


_MERGEABLE_POLLS = 5
_MERGEABLE_POLL_S = 2
_sleep = time.sleep


def _pr_refs(number: int) -> tuple[str, str]:
    base = f"refs/agentira/pr/{number}"
    return f"{base}/head", f"{base}/merge"


def integrate_pull_request(*, source_url: str, pr_number: int,
                           target_branch: str = "main",
                           verify_cmd: str = "",
                           verify_timeout_s: int = 1800,
                           merge_method: str = "merge",
                           github=None,
                           ) -> tuple[bool, str, dict | None]:
    """Run `verify_cmd` on PR #`pr_number`'s merge result, then merge the PR
    through GitHub. Never pushes to `target_branch` itself.

    Returns (ok, reason, verify). Failures carry a classified reason prefix:
    "merge_conflict", "pr_not_mergeable", "pr_head_moved", "pr_closed",
    "pr_base_mismatch", "verify_failed", "verify_timeout",
    "injected_files_committed", "github_unavailable", "clone_unavailable".
    `verify` is the check's result ({exit_code, duration_s, log_tail,
    timed_out}) or None when it did not run.
    """
    if not source_url:
        return False, "integration needs a source url", None
    if not pr_number:
        return False, "integration needs a pull request number", None
    github = github or GhCli()
    try:
        clone, _ = ensure_source_clone(source_url)
    except Exception as exc:  # noqa: BLE001 — classified upstream patterns
        return False, f"clone_unavailable: {exc}", None

    with _lock_for(clone):
        try:
            return _integrate_pr_locked(
                clone, source_url, pr_number, target_branch, verify_cmd,
                verify_timeout_s, merge_method, github)
        except GitHubError as exc:
            return False, f"github_unavailable: {exc}", None


def _pr_state_failure(pr: dict, target_branch: str) -> str | None:
    """Why the PR cannot be merged right now, or None if it can go on."""
    if pr["state"] != "open":
        return "pr_closed: the pull request was closed without being merged"
    if pr["base_ref"] != target_branch:
        return (f"pr_base_mismatch: the pull request targets '{pr['base_ref']}' "
                f"but the workflow merges into '{target_branch}'")
    if pr["mergeable"] is False or pr["mergeable_state"] == "dirty":
        return "merge_conflict: the pull request conflicts with the target branch"
    if pr["mergeable_state"] in ("blocked", "draft"):
        return (f"pr_not_mergeable: GitHub reports the pull request as "
                f"{pr['mergeable_state']}")
    return None


def _settled_pr_status(github, source_url: str, number: int) -> dict:
    """PR state once GitHub has finished computing mergeability (it answers
    `mergeable: null` for a moment after every push)."""
    for attempt in range(_MERGEABLE_POLLS):
        pr = github.pr_status(source_url, number)
        if pr["merged"] or pr["state"] != "open" or pr["mergeable"] is not None:
            return pr
        if attempt < _MERGEABLE_POLLS - 1:
            _sleep(_MERGEABLE_POLL_S)
    return pr


def _integrate_pr_locked(clone, source_url, number, target_branch, verify_cmd,
                         verify_timeout_s, merge_method, github):
    pr = _settled_pr_status(github, source_url, number)
    if pr["merged"]:
        return True, "merged", None
    if pr["mergeable"] is None and pr["state"] == "open":
        return False, ("pr_not_mergeable: GitHub has not finished checking "
                       "whether the pull request can be merged"), None
    failed = _pr_state_failure(pr, target_branch)
    if failed:
        return False, failed, None

    head_ref, merge_ref = _pr_refs(number)
    wt = Path(tempfile.mkdtemp(prefix="agentira-integrate-"))
    try:
        r = _git(clone, "fetch", "origin",
                 f"+refs/heads/{target_branch}:refs/remotes/origin/{target_branch}",
                 f"+refs/pull/{number}/head:{head_ref}",
                 f"+refs/pull/{number}/merge:{merge_ref}")
        if r.returncode != 0:
            return False, ("pr_not_mergeable: GitHub has no merge result for the "
                           f"pull request ({r.stderr.strip()[:200]})"), None

        # The merge result GitHub prepared must be built from the head that
        # will be merged; otherwise the check would prove different code.
        merge_parents = _git(clone, "rev-parse", f"{merge_ref}^2").stdout.strip()
        if pr["head_sha"] and merge_parents != pr["head_sha"]:
            return False, ("pr_head_moved: the pull request changed while it was "
                           "being checked"), None

        injected = _injected_files_added(clone, head_ref, target_branch)
        if injected:
            return False, f"injected_files_committed: {', '.join(injected)}", None

        r = _git(clone, "worktree", "add", "--detach", "--force", str(wt), merge_ref)
        if r.returncode != 0:
            return False, f"pr_not_mergeable: {r.stderr.strip()[:300]}", None

        verify = None
        if verify_cmd:
            verify = _run_verify(str(wt), verify_cmd, verify_timeout_s)
            failed = _verify_verdict(verify, verify_timeout_s)
            if failed:
                return False, failed, verify

        ok, kind, message = github.merge_pr(
            source_url, number, method=merge_method, sha=pr["head_sha"])
        if not ok:
            return False, f"{kind}: {message}", verify
        _git(clone, "fetch", "origin", f"{target_branch}:{target_branch}")
        logger.info("merged PR #%s into %s in %s (method=%s)",
                    number, target_branch, clone, merge_method)
        return True, "merged", verify
    finally:
        _git(clone, "worktree", "remove", "--force", str(wt))
        shutil.rmtree(wt, ignore_errors=True)
        for ref in (head_ref, merge_ref):
            _git(clone, "update-ref", "-d", ref)


def _injected_files_added(clone: str, branch: str, target_branch: str) -> list[str]:
    """Materializer-injected paths (conventions + courtesy links) the branch
    adds and the target doesn't track. Those were meant for the agent only;
    merging them would plant them in the project."""
    target = f"origin/{target_branch}"
    if _git(clone, "rev-parse", "--verify", target).returncode != 0:
        target = target_branch
    r = _git(clone, "diff", "--name-only", "--diff-filter=A",
             f"{target}...{branch}", "--", CONVENTIONS_REL, *COURTESY_NAMES)
    return [p for p in r.stdout.split()
            if _git(clone, "cat-file", "-e", f"{target}:{p}").returncode != 0]


_TAIL_LINES = 200


def _run_verify(cwd: str, cmd: str, timeout_s: int) -> dict:
    """Run the project's verify command in the merged tree. Output is bounded
    to the last `_TAIL_LINES` lines — it travels to the backend and onto the
    task feed, so a chatty test run must not become megabytes."""
    import time
    start = time.monotonic()
    try:
        p = subprocess.run(["/bin/sh", "-c", cmd], cwd=cwd, capture_output=True,
                           text=True, timeout=timeout_s)
        out, code, timed_out = (p.stdout or "") + (p.stderr or ""), p.returncode, False
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or b""
        out = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
        code, timed_out = None, True
    return {"exit_code": code,
            "duration_s": round(time.monotonic() - start, 1),
            "log_tail": "\n".join(out.splitlines()[-_TAIL_LINES:]),
            "timed_out": timed_out}


def _verify_verdict(verify: dict, timeout_s: int) -> str | None:
    """Classified failure reason, or None when the check passed."""
    if verify["timed_out"]:
        return f"verify_timeout: {timeout_s}s"
    if verify["exit_code"] != 0:
        return f"verify_failed: exit {verify['exit_code']}"
    return None
