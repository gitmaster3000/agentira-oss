"""Branch integration — deterministic merge of an approved task branch.

When a reviewer's run succeeds, the backend workflow driver sends an
`integrate` frame; this module merges the task's branch into the target
branch (main) **via the shared bare clone** (`~/.agentira/sources/<slug>`)
and pushes to origin. The bare clone is where every per-task worktree
branched from, so its refs already carry the task branches.

Merges run in a short-lived worktree off the bare master (bare repos have
no index / work tree, so `git checkout` + `git merge` cannot run in-place).

This is CODE doing a deterministic action with integrity guarantees (the
config decides *whether/where* to integrate; this module decides *nothing*):
- per-clone locking (no two merges race the same repo);
- merge --no-ff so each task lands as one auditable merge commit;
- any failure → merge abort + worktree cleanup, classified reason;
- push failure surfaces too (the remote is the source of truth other
  worktrees clone from).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from agentira_cli.daemon.materializer import CONVENTIONS_REL, COURTESY_NAMES
from agentira_cli.daemon.sources import (
    _is_bare,
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


def integrate_branch(*, source_url: str, branch: str,
                     target_branch: str = "main",
                     push: bool = True, verify_cmd: str = "",
                     verify_timeout_s: int = 1800,
                     ) -> tuple[bool, str, dict | None]:
    """Merge `branch` into `target_branch`, run `verify_cmd` on the merged
    tree (Loop v1 C6), and push to origin only if it passed.

    Shared clones are bare masters. Integration uses a temporary worktree
    checked out to `target_branch`, merges there, pushes, then removes the
    worktree.

    Returns (ok, reason, verify). On failure the bare clone is left clean;
    `reason` is a classified cause ("merge_conflict: …", "verify_failed: …",
    "verify_timeout: …", "push_failed: …", …). `verify` is the check's result
    ({exit_code, duration_s, log_tail, timed_out}) or None when not run.
    """
    if not source_url or not branch:
        return False, "integration needs both a source url and a branch", None
    try:
        clone, _ = ensure_source_clone(source_url)
    except Exception as exc:  # noqa: BLE001 — classified upstream patterns
        return False, f"clone_unavailable: {exc}", None

    with _lock_for(clone):
        # Refresh remote-tracking refs so origin/<target> is current.
        _git(clone, "fetch", "--prune", "origin")

        # Resolve target ref: prefer local heads, else origin/<target>.
        has_local = _git(clone, "rev-parse", "--verify", f"refs/heads/{target_branch}")
        if has_local.returncode != 0:
            has_remote = _git(
                clone, "rev-parse", "--verify", f"refs/remotes/origin/{target_branch}",
            )
            if has_remote.returncode != 0:
                return False, (
                    f"target_branch_unavailable: neither refs/heads/{target_branch} "
                    f"nor origin/{target_branch} exists"
                ), None
            # Create local target from remote-tracking so worktree can check it out.
            r = _git(
                clone, "branch", target_branch, f"origin/{target_branch}",
            )
            if r.returncode != 0:
                return False, f"target_branch_unavailable: {r.stderr.strip()[:300]}", None

        # Task branch must exist as a ref we can merge (local head or worktree).
        has_branch = _git(clone, "rev-parse", "--verify", branch)
        if has_branch.returncode != 0:
            has_branch = _git(clone, "rev-parse", "--verify", f"refs/heads/{branch}")
        if has_branch.returncode != 0:
            return False, f"branch_unavailable: {branch} not found in source clone", None

        injected = _injected_files_added(clone, branch, target_branch)
        if injected:
            return False, f"injected_files_committed: {', '.join(injected)}", None

        if not _is_bare(Path(clone)):
            # Legacy non-bare path (should be rare after bare migration).
            return _integrate_in_worktree(clone, branch, target_branch, push,
                                          verify_cmd, verify_timeout_s)

        return _integrate_via_temp_worktree(clone, branch, target_branch, push,
                                            verify_cmd, verify_timeout_s)


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


def _integrate_in_worktree(
    clone: str, branch: str, target_branch: str, push: bool,
    verify_cmd: str = "", verify_timeout_s: int = 1800,
) -> tuple[bool, str, dict | None]:
    for prep in (("checkout", target_branch), ("pull", "--ff-only", "origin", target_branch)):
        r = _git(clone, *prep)
        if r.returncode != 0 and prep[0] == "checkout":
            return False, f"target_branch_unavailable: {r.stderr.strip()[:300]}", None
    r = _git(
        clone,
        "-c", "user.name=Agentira", "-c", "user.email=bot@agentira.local",
        "merge", "--no-ff", "--no-edit", branch,
    )
    if r.returncode != 0:
        _git(clone, "merge", "--abort")
        err = (r.stdout + r.stderr).strip()[:300]
        if "CONFLICT" in r.stdout or "conflict" in err.lower():
            return False, f"merge_conflict: {err}", None
        return False, f"merge_failed: {err}", None
    verify = None
    if verify_cmd:
        verify = _run_verify(clone, verify_cmd, verify_timeout_s)
        failed = _verify_verdict(verify, verify_timeout_s)
        if failed:
            _git(clone, "reset", "--hard", "ORIG_HEAD")   # undo the merge
            return False, failed, verify
    if push:
        r = _git(clone, "push", "origin", target_branch)
        if r.returncode != 0:
            return False, f"push_failed: {r.stderr.strip()[:300]}", verify
    logger.info("integrated %s -> %s in %s (push=%s)",
                branch, target_branch, clone, push)
    return True, "merged", verify


def _integrate_via_temp_worktree(
    clone: str, branch: str, target_branch: str, push: bool,
    verify_cmd: str = "", verify_timeout_s: int = 1800,
) -> tuple[bool, str, dict | None]:
    """Merge on a temp worktree of the bare master, then push and remove it."""
    wt = Path(tempfile.mkdtemp(prefix="agentira-integrate-"))
    try:
        r = _git(
            clone, "worktree", "add", "--force", str(wt), target_branch,
        )
        if r.returncode != 0:
            return False, f"target_branch_unavailable: {r.stderr.strip()[:300]}", None

        # Fast-forward worktree target if origin moved ahead.
        _git(str(wt), "pull", "--ff-only", "origin", target_branch)
        # The worktree has the clone's real target branch checked out, so a
        # merge moves that ref. Remember where it was to undo a failed check.
        pre_merge = _git(str(wt), "rev-parse", "HEAD").stdout.strip()

        r = _git(
            str(wt),
            "-c", "user.name=Agentira", "-c", "user.email=bot@agentira.local",
            "merge", "--no-ff", "--no-edit", branch,
        )
        if r.returncode != 0:
            _git(str(wt), "merge", "--abort")
            err = (r.stdout + r.stderr).strip()[:300]
            if "CONFLICT" in r.stdout or "conflict" in err.lower():
                return False, f"merge_conflict: {err}", None
            return False, f"merge_failed: {err}", None

        # Loop v1 C6: prove the MERGED code works before anything leaves
        # this machine. Failure/timeout → nothing is pushed; the temp
        # worktree (and its merge commit) is discarded below.
        verify = None
        if verify_cmd:
            verify = _run_verify(str(wt), verify_cmd, verify_timeout_s)
            failed = _verify_verdict(verify, verify_timeout_s)
            if failed:
                # Undo the merge on the target ref — otherwise the next
                # integration would build on (and push) the failed merge.
                _git(str(wt), "reset", "--hard", pre_merge)
                return False, failed, verify

        if push:
            r = _git(str(wt), "push", "origin", f"HEAD:{target_branch}")
            if r.returncode != 0:
                return False, f"push_failed: {r.stderr.strip()[:300]}", verify

        # Keep bare clone's local target ref in sync with the merge.
        _git(clone, "fetch", "origin", f"{target_branch}:{target_branch}")

        logger.info("integrated %s -> %s in bare %s (push=%s)",
                    branch, target_branch, clone, push)
        return True, "merged", verify
    finally:
        # Always drop the temp worktree so the bare master stays clean.
        _git(clone, "worktree", "remove", "--force", str(wt))
        shutil.rmtree(wt, ignore_errors=True)
