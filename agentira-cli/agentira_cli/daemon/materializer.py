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

CONVENTIONS_ADDENDUM = (
    "Project conventions are in `.agentira/CONVENTIONS.md`. "
    "Read this file before starting any work."
)

MEMORY_ADDENDUM = (
    "You have a memory tool (knowledge graph) scoped to this project. "
    "At the start of a run, read what you already know about this project. "
    "Before finishing, write down decisions, gotchas, and lessons learned "
    "so future runs benefit. Memory is per-(agent, project) — what you "
    "store here won't leak into other projects."
)

# Kept for backward compatibility with anything that imported it directly.
SYSTEM_PROMPT_ADDENDUM = CONVENTIONS_ADDENDUM


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
                          have_conventions: bool,
                          have_memory: bool = False,
                          user_context: dict | None = None) -> str:
    """Prepend addenda so any runtime obeys them.

    Order: user-context preamble (AP-76) → conventions pointer → memory
    instruction → agent persona. The user-context preamble goes first so
    the agent knows where the user is BEFORE applying its persona — it
    disambiguates "this project" / "this task" / etc. for the rest of
    the prompt.
    """
    parts: list[str] = []
    if user_context:
        preamble = _render_user_context(user_context)
        if preamble:
            parts.append(preamble)
    if have_conventions:
        parts.append(CONVENTIONS_ADDENDUM)
    if have_memory:
        parts.append(MEMORY_ADDENDUM)
    if agent_system_prompt:
        parts.append(agent_system_prompt)
    return "\n\n".join(parts)


def _render_user_context(ctx: dict) -> str:
    """Render the per-call user-context dict as a system-message preamble.

    Tolerant: missing fields are skipped silently. Output stays short so
    it doesn't dominate context budget on small models.
    """
    if not isinstance(ctx, dict):
        return ""
    lines: list[str] = []
    surface = ctx.get("surface") or ""
    route = ctx.get("route") or ""
    project_name = ctx.get("project_name") or ""
    project_id = ctx.get("project_id") or ""
    task_title = ctx.get("task_title") or ""
    task_id = ctx.get("task_id") or ""

    where_bits: list[str] = []
    if surface:
        where_bits.append(surface)
    if project_name:
        where_bits.append(f"project '{project_name}'")
    elif project_id:
        where_bits.append(f"project {project_id}")
    if task_title:
        where_bits.append(f"task '{task_title}'")
    elif task_id:
        where_bits.append(f"task {task_id}")
    if route:
        where_bits.append(f"path={route}")

    if where_bits:
        lines.append(
            "The user is currently viewing: " + " · ".join(where_bits) + "."
        )

    nav = ctx.get("nav_history") or []
    if isinstance(nav, list) and nav:
        recent = [str(n) for n in nav[:5] if n]
        if recent:
            lines.append("Recent pages: " + " ← ".join(recent) + ".")

    if lines:
        lines.append(
            "When the user says \"this project\" / \"this task\", "
            "resolve it from the above before reading further instructions."
        )
    return "\n".join(lines)


def ensure_memory_dirs(mcp_config_json: str) -> None:
    """Pre-create parent dirs for any MEMORY_FILE_PATH the dispatch
    bundle declares. The memory MCP server can't create its own data
    directory — it expects the path to be writable on first call.

    Best-effort: silently swallow malformed JSON, missing keys, and
    permission errors. Whatever's missing will surface when the agent
    actually tries to write memory.
    """
    if not mcp_config_json:
        return
    import json
    try:
        cfg = json.loads(mcp_config_json)
    except (json.JSONDecodeError, TypeError):
        return
    servers = cfg.get("mcpServers") if isinstance(cfg, dict) else None
    if not isinstance(servers, dict):
        return
    for entry in servers.values():
        if not isinstance(entry, dict):
            continue
        env = entry.get("env") or {}
        path = env.get("MEMORY_FILE_PATH")
        if not path:
            continue
        try:
            from pathlib import Path as _Path
            parent = _Path(path).parent
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.debug("memory dir prep failed for %s: %s", path, exc)
