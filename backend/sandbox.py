"""AP-155: agent containment policy.

Phase 1 — config + resolver + dispatch wiring + daemon-side logging.
Actual enforcement (claude `--disallowedTools`, bubblewrap, Docker)
lands per-adapter in Phase 2 once the wiring is exercised.

**Where the value lives:**
- `Profile.sandbox_mode` is the agent's default containment posture.
  Identity drives security: trusted agents loose, experimental ones
  strict.
- `Project.sandbox_mode` is the project-level override. Set on a
  sensitive project, all agents tighten while inside it.
- Workspace default = "off" — no surprise restrictions on legacy work.

**Resolution chain (highest wins):**
    Project.sandbox_mode  →  Profile.sandbox_mode  →  "off"

**Modes:**
- `off`        — today's behavior. cwd set, nothing enforced.
- `cwd`        — claude `--add-dir <cwd>` + `--disallowedTools` blocks
                 obvious filesystem escapes. Best-effort; agent could
                 still subshell around it.
- `strict`     — OS sandbox (bubblewrap on Linux, sandbox-exec on Mac
                 best-effort). Filesystem outside `<cwd>` is invisible.
- `container`  — per-agent container with bind-mount only of `<cwd>` +
                 tool dirs. Strongest. Docker daemons only.

An adapter's capability set declares which modes it supports; the
resolver downshifts to the strongest mode ≤ requested that the adapter
can honor, logging the downshift so the user knows the request was
honored softer than asked.
"""

from __future__ import annotations

from typing import Iterable, Optional


# Ordered weakest → strongest. Higher index = stronger containment.
SANDBOX_MODES: tuple[str, ...] = ("off", "cwd", "strict", "container")

WORKSPACE_DEFAULT = "off"


def is_valid_mode(mode: Optional[str]) -> bool:
    return mode is None or mode in SANDBOX_MODES


def resolve_mode(
    *,
    project_mode: Optional[str],
    agent_mode: Optional[str],
    workspace_default: str = WORKSPACE_DEFAULT,
) -> str:
    """Pick the effective sandbox mode for a dispatch.

    Project override beats agent default beats workspace default.
    Returns one of the SANDBOX_MODES values (never None).
    """
    for candidate in (project_mode, agent_mode, workspace_default):
        if candidate and candidate in SANDBOX_MODES:
            return candidate
    return WORKSPACE_DEFAULT


def downshift_to_supported(
    *,
    requested: str,
    adapter_supports: Iterable[str],
) -> str:
    """Pick the strongest supported mode ≤ requested.

    If the adapter doesn't list "off" we still allow it — every adapter
    can do "nothing." If the adapter supports nothing weaker than
    requested, return "off" rather than block dispatch entirely; Phase 1
    is log-only so this is benign. Phase 2 may want to block.
    """
    supported = set(adapter_supports) | {"off"}
    try:
        target_strength = SANDBOX_MODES.index(requested)
    except ValueError:
        return WORKSPACE_DEFAULT
    # Walk down from requested looking for the strongest supported.
    for i in range(target_strength, -1, -1):
        candidate = SANDBOX_MODES[i]
        if candidate in supported:
            return candidate
    return WORKSPACE_DEFAULT
