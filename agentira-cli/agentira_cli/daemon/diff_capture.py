"""Capture `git diff` of a run's workdir on completion (AP-54, Phase F).

Why git only (and not generic file-state diffing)? The vast majority of
agent work happens against repos. For non-repo workdirs we'd need to
hash a snapshot before+after, which is a bigger and slower thing — punt
until someone asks.

Behavior:
- If the workdir isn't inside a git working tree, return ("", "").
- Run `git diff --stat` and `git diff` against HEAD (uncommitted changes
  the agent made during this run).
- Cap the full patch at MAX_DIFF_BYTES so a malicious or mistakenly
  generated giant diff doesn't blow up the DB row.
- Append a marker line when we trim so the human sees there was more.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("agentira.daemon.diff_capture")

MAX_DIFF_BYTES = 50_000  # ~50KB; readable in DB / UI, plenty for typical PRs
TRIM_NOTICE = "\n\n... [diff truncated; full patch exceeds 50KB] ..."


def capture(workdir: str | Path | None) -> tuple[str, str]:
    """Return (diff_stat, diff) for the workdir, or ("", "") if not a repo."""
    if not workdir:
        return "", ""
    cwd = Path(workdir)
    if not cwd.exists():
        return "", ""

    # Cheapest possible "is this a git repo?" check — bail fast if not.
    rev = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd)
    if rev is None or rev.strip() != "true":
        return "", ""

    # Strategy: diff committed work on the agent's branch (when the
    # branch has an upstream), else fall back to uncommitted changes vs
    # HEAD.
    #
    # NB: we deliberately do NOT fall back to diff-vs-empty-tree. For a
    # clean or freshly-committed working tree that would report the
    # repo's ENTIRE committed history as "the run's diff" — flooding the
    # run row with the whole codebase. A run's diff is what the agent
    # *changed*; pre-existing committed history is not that.
    diff_stat = ""
    diff_body = ""

    # 1. Upstream-based (only works when the branch has an upstream ref)
    upstream = _run(["git", "rev-parse", "--abbrev-ref", "@{upstream}"], cwd)
    if upstream:
        diff_stat = _run(["git", "diff", "--stat", "@{upstream}..HEAD"], cwd) or ""
        diff_body = _run(["git", "diff", "@{upstream}..HEAD"], cwd) or ""

    # 2. Uncommitted (vs HEAD)
    if not diff_body:
        diff_stat = _run(["git", "diff", "--stat"], cwd) or ""
        diff_body = _run(["git", "diff"], cwd) or ""

    if len(diff_body.encode("utf-8")) > MAX_DIFF_BYTES:
        diff_body = diff_body.encode("utf-8")[:MAX_DIFF_BYTES].decode(
            "utf-8", errors="ignore"
        ) + TRIM_NOTICE

    return diff_stat, diff_body


def _run(cmd: list[str], cwd: Path) -> str | None:
    """Run a git command, return stdout text or None on any failure."""
    try:
        out = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            logger.debug("git %s failed in %s: %s",
                         cmd[1:], cwd, out.stderr.strip())
            return None
        return out.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("git command unavailable / hung: %s", exc)
        return None
