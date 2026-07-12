"""Load CLI/daemon env vars from ~/.agentira/.env (shell vars win)."""

from __future__ import annotations

import os
from pathlib import Path


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key:
            out[key] = val
    return out


def load_env_file(path: Path) -> None:
    """Merge KEY=VALUE pairs from *path* into os.environ (no shell override)."""
    if not path.is_file():
        return
    for key, val in _parse_env_file(path).items():
        os.environ.setdefault(key, val)


def _cli_default_home() -> Path:
    return Path.home() / ".agentira"


def load_cli_env_files() -> None:
    """Load ~/.agentira/.env, then the active AGENTIRA_HOME/.env if different."""
    default_home = _cli_default_home()
    active_home = Path(os.environ.get("AGENTIRA_HOME") or default_home)
    load_env_file(default_home / ".env")
    if active_home != default_home:
        load_env_file(active_home / ".env")