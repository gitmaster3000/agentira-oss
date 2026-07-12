#!/usr/bin/env python3
"""Write backend/static/cli/manifest.json from the baked CLI wheel."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHEELS = ROOT / "backend" / "static" / "cli" / "wheels"
MANIFEST = ROOT / "backend" / "static" / "cli" / "manifest.json"
PYPROJECT = ROOT / "agentira-cli" / "pyproject.toml"

_VERSION_RE = re.compile(r'^version\s*=\s*"(?P<v>[^"]+)"', re.M)
_WHEEL_RE = re.compile(r"^agentira_cli-(?P<v>[\d.]+(?:\.\w+)?)-py3-none-any\.whl$")


def _version_from_pyproject() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    m = _VERSION_RE.search(text)
    if not m:
        raise SystemExit(f"could not read version from {PYPROJECT}")
    return m.group("v")


def main() -> None:
    wheels = sorted(WHEELS.glob("agentira_cli-*.whl"))
    if not wheels:
        raise SystemExit(f"no wheels in {WHEELS}")
    wheel = wheels[-1]
    m = _WHEEL_RE.match(wheel.name)
    version = m.group("v") if m else _version_from_pyproject()
    manifest = {
        "version": version,
        "min_python": "3.11",
        "wheel_filename": wheel.name,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST} ({version} → {wheel.name})")


if __name__ == "__main__":
    main()