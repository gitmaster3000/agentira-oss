"""Packaging smoke tests — catch missing declared dependencies before production.

Unit tests for OpenClaw WS mock out `import websocket` (see
test_openclaw_ws_logging.py) so they validate protocol logic, not install
health. CI job `cli-deps-smoke` runs this file as a script on a clean
`pip install -e ./agentira-cli` env (no pytest in the venv).

When adding a new hard import on a dispatch path, add an entry to
_RUNTIME_IMPORTS below and declare the package in agentira-cli/pyproject.toml.
"""

from __future__ import annotations

import importlib
import sys

# (import_name, attribute that must exist, why we need it)
_RUNTIME_IMPORTS: list[tuple[str, str, str]] = [
    (
        "websocket",
        "create_connection",
        "OpenClaw native WS (runtimes.openclaw_ws) and Forge OpenClawAdapter.chat",
    ),
    (
        "websockets.sync.client",
        "connect",
        "Daemon push client (ws_client) — backend trigger delivery",
    ),
]


def check_runtime_imports() -> list[str]:
    """Return human-readable failure lines (empty == all ok)."""
    failures: list[str] = []
    for module, attr, reason in _RUNTIME_IMPORTS:
        try:
            mod = importlib.import_module(module)
        except ImportError as exc:
            failures.append(
                f"MISSING {module!r} ({reason}): add package to "
                f"agentira-cli/pyproject.toml — {exc}"
            )
            continue
        if not hasattr(mod, attr):
            failures.append(
                f"BROKEN {module!r}: no {attr!r} — wrong package installed?"
            )
    return failures


def main() -> int:
    failures = check_runtime_imports()
    if failures:
        print("Runtime dependency smoke FAILED:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("Runtime dependency smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# Pytest collection only — below __main__ so `python test_runtime_deps.py`
# never needs pytest installed in the smoke venv.
import pytest  # noqa: E402


@pytest.mark.parametrize("module,attr,reason", _RUNTIME_IMPORTS)
def test_declared_runtime_import(module: str, attr: str, reason: str):
    """Each entry must import from the installed agentira-cli environment."""
    try:
        mod = importlib.import_module(module)
    except ImportError as exc:
        pytest.fail(
            f"Missing runtime dependency for {module!r} ({reason}). "
            f"Add the PyPI package to agentira-cli/pyproject.toml and "
            f"re-run `pip install -e ./agentira-cli`. Original: {exc}"
        )
    assert hasattr(mod, attr), (
        f"{module!r} imported but has no {attr!r} — wrong package installed?"
    )