"""AP-240: per-agent filesystem isolation.

The shared source clone + per-task worktrees architecture is intentional
(branches need to be visible across the implementer→reviewer hand-off, so
splitting clones would break review→merge). What was NEVER intentional
was leaving agent home dirs world-readable under the same Unix user, so
agent A could `cat ~/.agentira/agents/<B>/home/repos/.../task-*/some_file`
and read in-progress work directly.

This module owns one tiny job: ``chmod 0700`` on the agent's home root
the first time the daemon provisions for that agent, and on every dispatch
thereafter (idempotent). Container Phase 2 supersedes this when it lands;
until then this closes the easy-FS-read leak.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger("agentira.daemon.isolation")

# Root under which per-agent dirs live. Path is tilde-prefixed — callers
# never see an expanded path so this constant is testable cross-platform.
_AGENTS_ROOT_TMPL = "~/.agentira/agents"


def lockdown_agent_home(agent_id: str) -> bool:
    """Chmod 0700 on ``~/.agentira/agents/<agent_id>/`` (and the ``home``
    subdir if it exists). Idempotent — safe on every dispatch.

    Returns ``True`` if the lockdown succeeded OR was skipped because of
    platform (Windows POSIX mode bits don't apply). Returns ``False`` on a
    real OS error — the error is logged, never raised, because hardening
    must not break a dispatch.

    Empty ``agent_id`` is a degenerate input and returns ``False`` without
    touching the filesystem.
    """
    if not agent_id:
        return False
    if sys.platform.startswith("win"):
        return True
    agent_root = os.path.expanduser(f"{_AGENTS_ROOT_TMPL}/{agent_id}")
    try:
        os.makedirs(agent_root, exist_ok=True)
        os.chmod(agent_root, 0o700)
        # The dispatcher creates `<root>/home/...` lazily; tighten it the
        # moment it exists so subsequent reads through that path are gated
        # too. (The root chmod alone is sufficient against `cat` from
        # another agent, but a 0700 home is belt + braces and lets us hand
        # the agent its own dir without worrying about parent permissions.)
        home = os.path.join(agent_root, "home")
        if os.path.isdir(home):
            os.chmod(home, 0o700)
        return True
    except OSError as exc:
        logger.warning("AP-240: chmod 0700 on %s failed: %s",
                       agent_root, exc)
        return False
