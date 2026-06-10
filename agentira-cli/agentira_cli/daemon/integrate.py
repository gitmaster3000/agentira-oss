"""Branch integration — deterministic merge of an approved task branch.

When a reviewer's run succeeds, the backend workflow driver sends an
`integrate` frame; this module merges the task's branch into the target
branch (main) **in the shared clone** (`~/.agentira/sources/<slug>`) and
pushes to origin. The clone is where every per-task worktree branched from,
so its refs already carry the task branches — integration is local.

This is CODE doing a deterministic action with integrity guarantees (the
config decides *whether/where* to integrate; this module decides *nothing*):
- per-clone locking (no two merges race the same repo);
- merge --no-ff so each task lands as one auditable merge commit;
- any failure → `git merge --abort`, classified reason, repo left clean;
- push failure surfaces too (the remote is the source of truth other
  worktrees clone from).
"""

from __future__ import annotations

import logging
import subprocess

from agentira_cli.daemon.sources import ensure_source_clone, _lock_for, _git_env

logger = logging.getLogger("agentira.daemon.integrate")

_GIT_TIMEOUT = 120


def _git(clone: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", clone, *args],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT, env=_git_env(),
    )


def integrate_branch(*, source_url: str, branch: str,
                     target_branch: str = "main",
                     push: bool = True) -> tuple[bool, str]:
    """Merge `branch` into `target_branch` in the shared clone of `source_url`.

    Returns (ok, reason). On any failure the merge is aborted and the clone
    is left clean on `target_branch`; `reason` is a classified, human-readable
    cause ("merge_conflict: …", "push_failed: …", …).
    """
    if not source_url or not branch:
        return False, "integration needs both a source url and a branch"
    try:
        clone, _ = ensure_source_clone(source_url)
    except Exception as exc:  # noqa: BLE001 — classified upstream patterns
        return False, f"clone_unavailable: {exc}"

    with _lock_for(clone):
        # Land on the target branch with a clean tree.
        for prep in (("checkout", target_branch), ("pull", "--ff-only", "origin", target_branch)):
            r = _git(clone, *prep)
            if r.returncode != 0:
                # pull may fail for a just-seeded remote with no upstream
                # movement — only checkout failure is fatal.
                if prep[0] == "checkout":
                    return False, f"target_branch_unavailable: {r.stderr.strip()[:300]}"
        # --no-ff makes a merge commit, which needs a committer identity. Don't
        # rely on a global git config (absent on a fresh machine / in CI) — set
        # an explicit Agentira identity for the merge.
        r = _git(clone,
                 "-c", "user.name=Agentira", "-c", "user.email=bot@agentira.local",
                 "merge", "--no-ff", "--no-edit", branch)
        if r.returncode != 0:
            _git(clone, "merge", "--abort")
            err = (r.stdout + r.stderr).strip()[:300]
            if "CONFLICT" in r.stdout or "conflict" in err.lower():
                return False, f"merge_conflict: {err}"
            return False, f"merge_failed: {err}"
        if push:
            r = _git(clone, "push", "origin", target_branch)
            if r.returncode != 0:
                # The merge commit exists locally; the push is retryable.
                return False, f"push_failed: {r.stderr.strip()[:300]}"
        logger.info("integrated %s -> %s in %s (push=%s)",
                    branch, target_branch, clone, push)
        return True, "merged"
