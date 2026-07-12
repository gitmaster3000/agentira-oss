"""Tripwire: pairing method names + agent→operator.write stay true in installed OpenClaw.

Mirrors test_gateway_connect_contract.py — fails CI when OpenClaw drifts, not prod.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess

import pytest

from agentira_cli.runtimes.openclaw_scopes import PAIRING_METHODS, discover_write_scope


def _method_scopes_file() -> str | None:
    candidates: list[str] = []
    which = subprocess.run(["which", "openclaw"], capture_output=True, text=True)
    if which.returncode == 0:
        bindir = os.path.dirname(os.path.realpath(which.stdout.strip()))
        for rel in (
            "../lib/node_modules/openclaw/dist/method-scopes-*.js",
            "../../lib/node_modules/openclaw/dist/method-scopes-*.js",
        ):
            candidates += glob.glob(os.path.normpath(os.path.join(bindir, rel)))
    candidates += glob.glob("/opt/homebrew/lib/node_modules/openclaw/dist/method-scopes-*.js")
    candidates += glob.glob(os.path.expanduser(
        "~/.openclaw/plugin-runtime-deps/openclaw-*/dist/method-scopes-*.js"
    ))
    return sorted(candidates, reverse=True)[0] if candidates else None


def test_pairing_method_names_still_exported():
    path = _method_scopes_file()
    if not path:
        pytest.skip("OpenClaw not installed")
    js = open(path, encoding="utf-8").read()
    for name in PAIRING_METHODS:
        assert f'"{name}"' in js, f"{name} missing from {path}"
    # Device pairing is connect-handshake driven — this RPC must not appear.
    assert '"device.pair.request"' not in js


def test_agent_requires_operator_write():
    path = _method_scopes_file()
    if not path:
        pytest.skip("OpenClaw not installed")
    assert discover_write_scope() == "operator.write"
    js = open(path, encoding="utf-8").read()
    assert '"agent"' in js
    assert "operator.write" in js
    # WRITE_SCOPE list should include agent (order varies in minified output).
    m = re.search(
        r'\[WRITE_SCOPE\]:\s*\[([\s\S]*?)\]\s*,\s*\[ADMIN_SCOPE\]',
        js,
    )
    if m:
        assert '"agent"' in m.group(1)
