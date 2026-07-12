"""Contract test: our gateway connect params must stay valid against the
*installed* OpenClaw's enums.

Why this exists: we hand-roll the OpenClaw gateway WS handshake in Python
(daemon executor + backend adapter). OpenClaw validates `client.id` and
`client.mode` as strict enums and negotiates a protocol version range. When
we invent values (the `forge` / `agentira-daemon` / `operator` regression) or
pin a protocol the server dropped, connect fails at runtime in prod.

This test is the tripwire: it reads OpenClaw's own enum source from the
installed package and fails the moment our canonical values stop being
members — so a bad OpenClaw upgrade breaks CI, not production.
"""
from __future__ import annotations

import glob
import os
import re

import pytest

from agentira_cli.runtimes.gateway_connect import (
    GATEWAY_CLIENT_ID,
    GATEWAY_CLIENT_MODE,
    MAX_PROTOCOL,
    MIN_PROTOCOL,
    build_connect_params,
)

# OpenClaw ships its protocol constants in a bundled JS module named
# message-channel-*.js under the plugin-runtime-deps install dir.
_ENUM_GLOB = os.path.expanduser(
    "~/.openclaw/plugin-runtime-deps/openclaw-*/dist/message-channel-*.js"
)
# Server accepts a connect iff maxProtocol >= 3 and minProtocol <= 3 today.
_SERVER_PROTOCOL = 3


def _installed_enum_file() -> str | None:
    for path in sorted(glob.glob(_ENUM_GLOB), reverse=True):
        with open(path, encoding="utf-8") as f:
            if "GATEWAY_CLIENT_IDS = {" in f.read():
                return path
    return None


def _parse_enum(js: str, name: str) -> set[str]:
    """Extract the string values from `const <name> = { KEY: "val", ... }`."""
    m = re.search(name + r"\s*=\s*\{(.*?)\}", js, re.DOTALL)
    assert m, f"{name} not found in installed OpenClaw enum file"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_connect_params_use_canonical_identity():
    """Unit: the frame we send carries the canonical backend identity."""
    params = build_connect_params("tok")
    assert params["client"]["id"] == GATEWAY_CLIENT_ID == "gateway-client"
    assert params["client"]["mode"] == GATEWAY_CLIENT_MODE == "backend"
    assert params["auth"] == {"token": "tok"}


def test_protocol_range_brackets_server():
    """Offered range must include the server's protocol (negotiation, not a pin)."""
    assert MIN_PROTOCOL <= _SERVER_PROTOCOL <= MAX_PROTOCOL


def test_identity_still_valid_in_installed_openclaw():
    """Drift tripwire: canonical id/mode must remain members of OpenClaw's enums."""
    enum_file = _installed_enum_file()
    if not enum_file:
        pytest.skip("OpenClaw not installed on this machine")
    js = open(enum_file, encoding="utf-8").read()
    ids = _parse_enum(js, "GATEWAY_CLIENT_IDS")
    modes = _parse_enum(js, "GATEWAY_CLIENT_MODES")
    assert GATEWAY_CLIENT_ID in ids, (
        f"{GATEWAY_CLIENT_ID!r} dropped from OpenClaw GATEWAY_CLIENT_IDS={sorted(ids)}"
    )
    assert GATEWAY_CLIENT_MODE in modes, (
        f"{GATEWAY_CLIENT_MODE!r} dropped from OpenClaw GATEWAY_CLIENT_MODES={sorted(modes)}"
    )
