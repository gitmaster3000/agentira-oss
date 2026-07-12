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
                     push: bool = True) -> tuple[bool, str]:
    """Merge `branch` into `target_branch` and push to origin.

    Shared clones are bare masters. Integration uses a temporary worktree
    checked out to `target_branch`, merges there, pushes, then removes the
    worktree.

    Returns (ok, reason). On failure the bare clone is left clean;
    `reason` is a classified cause ("merge_conflict: …", "push_failed: …", …).
    """
    if not source_url or not branch:
        return False, "integration needs both a source url and a branch"
    try:
        clone, _ = ensure_source_clone(source_url)
    except Exception as exc:  # noqa: BLE001 — classified upstream patterns
        return False, f"clone_unavailable: {exc}"

    with _lock_for(clone):
        # Refresh remote-tracking refs so origin/<target> is current.
        _git(clone, "fetch", "--prune", "origin")

        # Resolve target ref: prefer local heads, else origin/<target>.
        target_ref = target_branch
        has_local = _git(clone, "rev-parse", "--verify", f"refs/heads/{target_branch}")
        if has_local.returncode != 0:
            has_remote = _git(
                clone, "rev-parse", "--verify", f"refs/remotes/origin/{target_branch}",
            )
            if has_remote.returncode != 0:
                return False, (
                    f"target_branch_unavailable: neither refs/heads/{target_branch} "
                    f"nor origin/{target_branch} exists"
                )
            # Create local target from remote-tracking so worktree can check it out.
            r = _git(
                clone, "branch", target_branch, f"origin/{target_branch}",
            )
            if r.returncode != 0:
                return False, f"target_branch_unavailable: {r.stderr.strip()[:300]}"

        # Task branch must exist as a ref we can merge (local head or worktree).
        has_branch = _git(clone, "rev-parse", "--verify", branch)
        if has_branch.returncode != 0:
            has_branch = _git(clone, "rev-parse", "--verify", f"refs/heads/{branch}")
        if has_branch.returncode != 0:
            return False, f"branch_unavailable: {branch} not found in source clone"

        if not _is_bare(Path(clone)):
            # Legacy non-bare path (should be rare after bare migration).
            return _integrate_in_worktree(clone, branch, target_branch, push)

        return _integrate_via_temp_worktree(clone, branch, target_branch, push)


def _integrate_in_worktree(
    clone: str, branch: str, target_branch: str, push: bool,
) -> tuple[bool, str]:
    for prep in (("checkout", target_branch), ("pull", "--ff-only", "origin", target_branch)):
        r = _git(clone, *prep)
        if r.returncode != 0 and prep[0] == "checkout":
            return False, f"target_branch_unavailable: {r.stderr.strip()[:300]}"
    r = _git(
        clone,
        "-c", "user.name=Agentira", "-c", "user.email=bot@agentira.local",
        "merge", "--no-ff", "--no-edit", branch,
    )
    if r.returncode != 0:
        _git(clone, "merge", "--abort")
        err = (r.stdout + r.stderr).strip()[:300]
        if "CONFLICT" in r.stdout or "conflict" in err.lower():
            return False, f"merge_conflict: {err}"
        return False, f"merge_failed: {err}"
    if push:
        r = _git(clone, "push", "origin", target_branch)
        if r.returncode != 0:
            return False, f"push_failed: {r.stderr.strip()[:300]}"
    logger.info("integrated %s -> %s in %s (push=%s)",
                branch, target_branch, clone, push)
    return True, "merged"


def _integrate_via_temp_worktree(
    clone: str, branch: str, target_branch: str, push: bool,
) -> tuple[bool, str]:
    """Merge on a temp worktree of the bare master, then push and remove it."""
    wt = Path(tempfile.mkdtemp(prefix="agentira-integrate-"))
    try:
        r = _git(
            clone, "worktree", "add", "--force", str(wt), target_branch,
        )
        if r.returncode != 0:
            return False, f"target_branch_unavailable: {r.stderr.strip()[:300]}"

        # Fast-forward worktree target if origin moved ahead.
        _git(str(wt), "pull", "--ff-only", "origin", target_branch)

        r = _git(
            str(wt),
            "-c", "user.name=Agentira", "-c", "user.email=bot@agentira.local",
            "merge", "--no-ff", "--no-edit", branch,
        )
        if r.returncode != 0:
            _git(str(wt), "merge", "--abort")
            err = (r.stdout + r.stderr).strip()[:300]
            if "CONFLICT" in r.stdout or "conflict" in err.lower():
                return False, f"merge_conflict: {err}"
            return False, f"merge_failed: {err}"

        if push:
            r = _git(str(wt), "push", "origin", f"HEAD:{target_branch}")
            if r.returncode != 0:
                return False, f"push_failed: {r.stderr.strip()[:300]}"

        # Keep bare clone's local target ref in sync with the merge.
        _git(clone, "fetch", "origin", f"{target_branch}:{target_branch}")

        logger.info("integrated %s -> %s in bare %s (push=%s)",
                    branch, target_branch, clone, push)
        return True, "merged"
    finally:
        # Always drop the temp worktree so the bare master stays clean.
        _git(clone, "worktree", "remove", "--force", str(wt))
        shutil.rmtree(wt, ignore_errors=True)
