"""Materialize the run-context bundle (AP-52, Phase D).

Given the dispatch frame's bundle (repo_path, conventions_md, …), set up
the per-task workdir so the spawned CLI agent wakes up oriented:

  workdir/
    .agentira/CONVENTIONS.md   — project conventions, runtime-agnostic
    AGENTS.md  → CONVENTIONS.md  (courtesy symlink, only if absent)
    CLAUDE.md  → CONVENTIONS.md
    GEMINI.md  → CONVENTIONS.md
    repo/      → repo_path        (symlink, only when repo_path set)

If repo_path is set, we run the CLI with cwd = repo_path directly so the
agent is *in* the repo (so its filesystem MCP tool sees git history,
existing files, etc.). The .agentira/CONVENTIONS.md and the courtesy
symlinks land in repo_path itself when there's a repo, or in the
workdir otherwise.

The system_prompt addendum is a plain English instruction so any
runtime — claude, codex, gemini, future ones — can follow it without
relying on per-runtime magic filenames (CLAUDE.md auto-discovery, etc.).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from agentira_cli.daemon.workdir import task_workdir

logger = logging.getLogger("agentira.daemon.materializer")

CONVENTIONS_REL = ".agentira/CONVENTIONS.md"
COURTESY_NAMES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")

SYSTEM_PROMPT_ADDENDUM = (
    "Project conventions are in `.agentira/CONVENTIONS.md`. "
    "Read this file before starting any work."
)


def materialize(
    *,
    workspace_id: str,
    task_id: str,
    repo_path: str = "",
    conventions_md: str = "",
) -> tuple[Path, Path]:
    """Set up the run environment.

    Returns (cwd, conventions_dir) where:
      cwd               — what to pass as subprocess cwd (repo_path if set,
                          else the per-task workdir)
      conventions_dir   — directory the conventions file was written to
                          (matches cwd in the common case)

    Idempotent: callers can re-invoke; we never overwrite a CONVENTIONS.md
    that already matches, never replace user-authored AGENTS.md/CLAUDE.md.
    """
    workdir = task_workdir(workspace_id, task_id)

    # Where the agent runs: in the repo if we have one, else the scratch
    # workdir. Running inside repo_path is critical — the agent needs to
    # see git history and existing files to work meaningfully.
    if repo_path:
        cwd = Path(os.path.expanduser(repo_path)).resolve()
        if not cwd.exists():
            logger.warning(
                "repo_path %s does not exist — falling back to workdir %s",
                repo_path, workdir,
            )
            cwd = workdir
    else:
        cwd = workdir

    if conventions_md:
        _write_conventions(cwd, conventions_md)
        _link_courtesy_files(cwd)

    return cwd, cwd


def _write_conventions(cwd: Path, content: str) -> None:
    """Write .agentira/CONVENTIONS.md atomically. Skip if unchanged."""
    target = cwd / CONVENTIONS_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if target.exists() and target.read_text(encoding="utf-8") == content:
            return  # no-op write
    except (OSError, UnicodeDecodeError):
        pass
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target)


def _link_courtesy_files(cwd: Path) -> None:
    """Drop AGENTS.md / CLAUDE.md / GEMINI.md as symlinks pointing at the
    canonical .agentira/CONVENTIONS.md, but only when the runtime-specific
    file doesn't already exist. Repos that ship their own AGENTS.md keep
    full control — we never overwrite team intent."""
    for name in COURTESY_NAMES:
        link = cwd / name
        if link.exists() or link.is_symlink():
            continue   # respect existing files / symlinks
        try:
            link.symlink_to(CONVENTIONS_REL)
        except OSError as exc:
            logger.debug("courtesy symlink %s skipped: %s", name, exc)


def compose_system_prompt(agent_system_prompt: str, *,
                          have_conventions: bool) -> str:
    """Prepend the addendum so any runtime obeys it.

    `have_conventions` lets us skip the addendum when no conventions were
    materialized — pointing the agent at a non-existent file is worse
    than not pointing at all.
    """
    parts: list[str] = []
    if have_conventions:
        parts.append(SYSTEM_PROMPT_ADDENDUM)
    if agent_system_prompt:
        parts.append(agent_system_prompt)
    return "\n\n".join(parts)
