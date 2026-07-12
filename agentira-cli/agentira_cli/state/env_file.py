"""Load CLI/daemon env from ~/.agentira/.env.

Config priority (highest first):
  1. CLI flags (per command)
  2. Environment variables (one-shot or container — NOT shell profiles)
  3. Config file(s): ~/.agentira/.env, then ~/.agentira-test/.env if active
  4. Code defaults

Put persistent settings in ~/.agentira/.env only. Do not export AGENTIRA_*
in ~/.zshrc — use inline env for one-off overrides: AGENTIRA_DEV_MODE=1 agentira …
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_AGENTIRA_PREFIX = "AGENTIRA_"


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


def _env_label(path: Path) -> str:
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def _shell_override_warnings(
    initial: dict[str, str],
    file_vars: dict[str, str],
    env_path: Path,
) -> list[str]:
    if not initial:
        return []
    label = _env_label(env_path)
    out: list[str] = []
    for key, shell_val in sorted(initial.items()):
        if key not in file_vars:
            out.append(
                f"{key} is set in your shell but not in {label}. "
                f"Environment wins — remove it from ~/.zshrc and use {label} instead."
            )
        elif file_vars[key] != shell_val:
            out.append(
                f"{key} in shell ({shell_val!r}) overrides {label} "
                f"({file_vars[key]!r}). Environment wins — unset it or remove "
                f"from ~/.zshrc."
            )
    return out


def _snapshot_agentira_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.startswith(_AGENTIRA_PREFIX)}


def _apply_file_layers(
    default_vars: dict[str, str],
    active_vars: dict[str, str],
    *,
    active_differs: bool,
    initial: dict[str, str],
) -> None:
    """Apply file values only where the shell did not already set them."""
    for key, val in default_vars.items():
        if key not in initial:
            os.environ.setdefault(key, val)
    if active_differs:
        for key, val in active_vars.items():
            if key not in initial:
                os.environ[key] = val


def load_cli_env_files() -> list[str]:
    """Load .env files (env beats file). Return shell-profile warnings."""
    initial = _snapshot_agentira_env()
    default_home = _cli_default_home()
    active_home = Path(os.environ.get("AGENTIRA_HOME") or default_home)
    default_path = default_home / ".env"
    active_path = active_home / ".env"
    active_differs = active_home != default_home

    default_vars = _parse_env_file(default_path) if default_path.is_file() else {}
    active_vars = (
        _parse_env_file(active_path) if active_differs and active_path.is_file() else {}
    )
    merged_file = {**default_vars, **active_vars} if active_differs else default_vars

    warnings = _shell_override_warnings(initial, merged_file, default_path)
    _apply_file_layers(
        default_vars, active_vars, active_differs=active_differs, initial=initial,
    )
    return warnings


def emit_config_warnings(warnings: list[str]) -> None:
    for msg in warnings:
        print(f"warning: {msg}", file=sys.stderr)


def _cli_default_home() -> Path:
    return Path.home() / ".agentira"