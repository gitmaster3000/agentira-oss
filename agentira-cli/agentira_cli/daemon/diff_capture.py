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

# AP-149 — Paths that must NEVER count as agent work, no matter where they
# appear (tracked, untracked, committed). Two reasons:
#
#   (1) Materializer-owned files — Agentira itself drops these into the cwd
#       at dispatch (`.agentira/CONVENTIONS.md` + courtesy CLAUDE.md /
#       AGENTS.md / GEMINI.md symlinks). If the user accidentally commits
#       any of them, a re-run that rewrites them would otherwise crystallize
#       a fake run.
#
#   (2) Common scratch / build / cache directories. A brand-new project
#       without a complete `.gitignore` would otherwise crystallize a run
#       from `npm install` side-effects (node_modules), `__pycache__/`,
#       compiled outputs (`dist/`, `build/`), virtualenvs, etc. The user can
#       still add their own .gitignore; this is Agentira being defensive about
#       opinionated scratch on its first-project loop.
#
# Applied via git pathspec exclusion (`:(exclude)<path>`) to every diff /
# ls-files call so the filter is identical for tracked, untracked, and
# committed work.
_EXCLUDED_PATHS = (
    # Materializer-owned (always)
    ".agentira/",
    "AGENTS.md", "CLAUDE.md", "GEMINI.md",
    # Common scratch / build / cache dirs
    "node_modules/",
    "__pycache__/", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
    ".cache/",
    ".venv/", "venv/", "env/",
    "dist/", "build/", "target/", "out/", ".next/", ".nuxt/",
    ".tox/", ".nox/", ".gradle/",
    # OS detritus
    ".DS_Store", "Thumbs.db",
)

# git pathspec args — passed after `--` on every git diff/ls-files call.
_EXCLUDE_PATHSPECS = [f":(exclude){p}" for p in _EXCLUDED_PATHS]


def capture(workdir: str | Path | None) -> tuple[str, str]:
    """Return (diff_stat, diff) — back-compat 2-tuple for existing callers."""
    diff_stat, diff_body, _facts = capture_with_signal(workdir)
    return diff_stat, diff_body


def capture_with_signal(
    workdir: str | Path | None,
) -> tuple[str, str, dict]:
    """Return (diff_stat, diff, facts).

    facts = {
        "tracked": bool,         # tracked-file edits exist (committed or not)
        "untracked": bool,       # new untracked files exist (post-exclusion)
        "committed": bool,       # commits exist vs upstream
        "lines_changed": int,    # +/- lines in the tracked diff (AP-149)
        "files_changed": int,    # unique tracked files touched (AP-149)
        "untracked_count": int,  # untracked file count post-exclusion (AP-149)
    } — the raw git observations the backend maps onto the project's
    work-signal setting (working_tree | tracked | committed) to decide run
    crystallization. The three diagnostic counts are for sanity-checking and
    future tuning; they don't change crystallization behavior today.

    AP-149: exclusions in `_EXCLUDED_PATHS` are applied via git pathspec to
    every git call, so a materializer-owned file that *is* tracked, or a
    new `node_modules/` from a fresh `npm install`, is never credited as
    agent work.
    """
    empty_facts = {"tracked": False, "untracked": False, "committed": False,
                   "lines_changed": 0, "files_changed": 0, "untracked_count": 0}
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
        diff_stat = _run(["git", "diff", "--stat", "@{upstream}..HEAD",
                          "--", *_EXCLUDE_PATHSPECS], cwd) or ""
        diff_body = _run(["git", "diff", "@{upstream}..HEAD",
                          "--", *_EXCLUDE_PATHSPECS], cwd) or ""
        committed = bool(diff_body.strip())

    # 2. Uncommitted tracked changes (vs HEAD)
    uncommitted_body = _run(["git", "diff", "--", *_EXCLUDE_PATHSPECS], cwd) or ""
    if uncommitted_body.strip():
        tracked = True
        if not diff_body:
            diff_stat = _run(["git", "diff", "--stat", "--", *_EXCLUDE_PATHSPECS], cwd) or ""
            diff_body = uncommitted_body
    tracked = tracked or committed

    # 3. Diagnostic counts (AP-149) on the tracked diff, BEFORE we append the
    # untracked listing — `lines_changed` reflects code edits only; untracked
    # files contribute via `untracked_count` not lines.
    lines_changed = _count_diff_lines(diff_body)
    files_changed = _count_changed_files(cwd, upstream)

    # 4. NEW untracked files (respect .gitignore via --exclude-standard
    #    AND our exclusion pathspecs). Surface them in the diff so nothing
    #    the agent created is silently lost.
    untracked_files = _untracked_files(cwd)
    untracked_count = len(untracked_files)
    if untracked_files:
        listing = "\n".join(f"  + {p}" for p in untracked_files)
        diff_stat = (diff_stat + f"\n{untracked_count} new untracked file(s)\n").lstrip("\n")
        diff_body = (diff_body + "\n\n# New untracked files (not yet committed):\n"
                     + listing).lstrip("\n")

    if len(diff_body.encode("utf-8")) > MAX_DIFF_BYTES:
        diff_body = diff_body.encode("utf-8")[:MAX_DIFF_BYTES].decode(
            "utf-8", errors="ignore"
        ) + TRIM_NOTICE

    facts = {
        "tracked": tracked, "untracked": bool(untracked_files),
        "committed": committed,
        "lines_changed": lines_changed,
        "files_changed": files_changed,
        "untracked_count": untracked_count,
    }
    return diff_stat, diff_body, facts


def _count_diff_lines(diff_body: str) -> int:
    """Sum of `+`/`-` lines in a diff body, excluding `+++`/`---` headers.

    Doesn't double-count the "Untracked files" section we append later —
    those lines start with `  + ` (two spaces) so `startswith("+")` is False.
    """
    if not diff_body:
        return 0
    n = 0
    for line in diff_body.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            n += 1
    return n


def _count_changed_files(cwd: Path, upstream: str | None) -> int:
    """How many unique tracked files were changed (committed + uncommitted),
    post-exclusion. One small extra git call for accuracy; we use --name-only
    instead of parsing --shortstat because we already strip excluded paths."""
    files: set[str] = set()
    if upstream:
        out = _run(["git", "diff", "--name-only", "@{upstream}..HEAD",
                    "--", *_EXCLUDE_PATHSPECS], cwd) or ""
        files.update(p for p in (ln.strip() for ln in out.splitlines()) if p)
    out = _run(["git", "diff", "--name-only", "--", *_EXCLUDE_PATHSPECS], cwd) or ""
    files.update(p for p in (ln.strip() for ln in out.splitlines()) if p)
    return len(files)


def _untracked_files(cwd: Path) -> list[str]:
    """New, non-ignored files the agent created, post-exclusion.

    `--exclude-standard` honors .gitignore/.git/info/exclude; our own
    `:(exclude)` pathspecs add a defensive opinionated layer for materializer
    files and common scratch dirs (AP-149) so a repo without a complete
    .gitignore doesn't crystallize a run from npm-install / pyc / etc."""
    out = _run(["git", "ls-files", "--others", "--exclude-standard",
                "--", *_EXCLUDE_PATHSPECS], cwd)
    if not out:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


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
