"""Capture `git diff` of a run's workdir on completion (AP-54, Phase F).

Why git only (and not generic file-state diffing)? The vast majority of
agent work happens against repos. For non-repo workdirs we'd need to
hash a snapshot before+after, which is a bigger and slower thing — punt
until someone asks.

Behavior:
- If the workdir isn't inside a git working tree, return empty.
- Capture committed work (vs upstream) when the branch has an upstream,
  else uncommitted tracked changes (vs HEAD).
- ADR 009: ALSO surface NEW untracked files (respecting .gitignore, and
  excluding the materializer's own `.agentira/*`), so a file the agent
  created but didn't `git add` is never silently lost — and so the
  `working_tree` work-signal can see it.
- Cap the full patch at MAX_DIFF_BYTES so a giant diff can't blow up the
  DB row; append a marker line when we trim.

`capture_with_signal` additionally returns work-signal facts the backend
uses to decide whether a turn crystallizes into a run (ADR 009 / AP-136):
{"tracked": bool, "untracked": bool, "committed": bool}.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("agentira.daemon.diff_capture")

MAX_DIFF_BYTES = 50_000  # ~50KB; readable in DB / UI, plenty for typical PRs
TRIM_NOTICE = "\n\n... [diff truncated; full patch exceeds 50KB] ..."

# The materializer drops these into the cwd; they must never count as the
# agent's work nor pollute the displayed diff.
_EXCLUDE_PREFIXES = (".agentira/", "AGENTS.md", "CLAUDE.md", "GEMINI.md")


def capture(workdir: str | Path | None) -> tuple[str, str]:
    """Return (diff_stat, diff) — back-compat 2-tuple for existing callers."""
    diff_stat, diff_body, _facts = capture_with_signal(workdir)
    return diff_stat, diff_body


def capture_with_signal(
    workdir: str | Path | None,
) -> tuple[str, str, dict]:
    """Return (diff_stat, diff, facts).

    facts = {"tracked": bool, "untracked": bool, "committed": bool} — the
    raw git observations the backend maps onto the project's work-signal
    setting (working_tree | tracked | committed) to decide run crystallization.
    """
    empty_facts = {"tracked": False, "untracked": False, "committed": False}
    if not workdir:
        return "", "", dict(empty_facts)
    cwd = Path(workdir)
    if not cwd.exists():
        return "", "", dict(empty_facts)

    # Cheapest possible "is this a git repo?" check — bail fast if not.
    rev = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd)
    if rev is None or rev.strip() != "true":
        return "", "", dict(empty_facts)

    # Strategy: diff committed work on the agent's branch (when the
    # branch has an upstream), else fall back to uncommitted changes vs
    # HEAD. We deliberately do NOT diff-vs-empty-tree (that would report
    # the whole codebase as "the run's diff").
    diff_stat = ""
    diff_body = ""
    committed = False
    tracked = False

    # 1. Committed work the agent hasn't pushed (upstream..HEAD)
    upstream = _run(["git", "rev-parse", "--abbrev-ref", "@{upstream}"], cwd)
    if upstream:
        diff_stat = _run(["git", "diff", "--stat", "@{upstream}..HEAD"], cwd) or ""
        diff_body = _run(["git", "diff", "@{upstream}..HEAD"], cwd) or ""
        committed = bool(diff_body.strip())

    # 2. Uncommitted tracked changes (vs HEAD)
    uncommitted_body = _run(["git", "diff"], cwd) or ""
    if uncommitted_body.strip():
        tracked = True
        if not diff_body:
            diff_stat = _run(["git", "diff", "--stat"], cwd) or ""
            diff_body = uncommitted_body
    tracked = tracked or committed

    # 3. NEW untracked files (respect .gitignore via --exclude-standard,
    #    then drop our own materializer files). Surface them in the diff
    #    so nothing the agent created is silently lost.
    untracked_files = _untracked_files(cwd)
    if untracked_files:
        listing = "\n".join(f"  + {p}" for p in untracked_files)
        diff_stat = (diff_stat + f"\n{len(untracked_files)} new untracked file(s)\n").lstrip("\n")
        diff_body = (diff_body + "\n\n# New untracked files (not yet committed):\n"
                     + listing).lstrip("\n")

    if len(diff_body.encode("utf-8")) > MAX_DIFF_BYTES:
        diff_body = diff_body.encode("utf-8")[:MAX_DIFF_BYTES].decode(
            "utf-8", errors="ignore"
        ) + TRIM_NOTICE

    facts = {"tracked": tracked, "untracked": bool(untracked_files),
             "committed": committed}
    return diff_stat, diff_body, facts


def _untracked_files(cwd: Path) -> list[str]:
    """New, non-ignored files the agent created, excluding materializer
    artifacts. `--exclude-standard` honors .gitignore/.git/info/exclude."""
    out = _run(["git", "ls-files", "--others", "--exclude-standard"], cwd)
    if not out:
        return []
    files = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return [f for f in files
            if not any(f == p or f.startswith(p) for p in _EXCLUDE_PREFIXES)]


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
