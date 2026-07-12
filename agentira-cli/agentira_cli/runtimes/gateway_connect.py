"""Canonical OpenClaw gateway connect frame — one source of truth.

OpenClaw validates `client.id` / `client.mode` as strict enums and negotiates
a protocol version *range*. We used to hand-copy invented values (`forge` /
`agentira-daemon` + `operator`) into every WS handshake and pin a single
protocol; both broke when OpenClaw tightened validation / only spoke v3.

The values below are OpenClaw's OWN defaults for a backend caller
(`GATEWAY_CLIENT_NAMES.GATEWAY_CLIENT` = "gateway-client",
`GATEWAY_CLIENT_MODES.BACKEND` = "backend"), and the gateway special-cases
exactly this pair as the trusted server-to-server identity — the least
churn-prone contract we can pick. `test_gateway_connect_contract.py` asserts
they stay members of the installed enum set, so a bad upgrade fails CI.

Protocol is offered as a range so the gateway negotiates rather than us
pinning: the server today rejects unless minProtocol <= 3 <= maxProtocol.
"""
from __future__ import annotations

import platform as _platform
from typing import Any, Optional

GATEWAY_CLIENT_ID = "gateway-client"
GATEWAY_CLIENT_MODE = "backend"
# Offer a range; the gateway picks. Bump MAX after verifying a new protocol —
# the contract test flags when the server moves past this window.
MIN_PROTOCOL = 3
MAX_PROTOCOL = 4
CLIENT_VERSION = "2026.7"


def build_connect_params(
    token: str,
    *,
    user_agent: str = "agentira",
    auth_kind: str = "token",
    device: Optional[dict] = None,
    scopes: Optional[list[str]] = None,
    client_id: Optional[str] = None,
    client_mode: Optional[str] = None,
    display_name: Optional[str] = None,
) -> dict:
    """Full `connect` params for an OpenClaw gateway WS handshake.

    auth_kind:
      - "token": shared gateway.auth.token (registration / admin only)
      - "deviceToken": issued device token (execution)
    """
    auth: dict[str, Any] = {}
    if token:
        if auth_kind == "deviceToken":
            auth = {"deviceToken": token}
        else:
            auth = {"token": token}
    client: dict[str, Any] = {
        "id": client_id or GATEWAY_CLIENT_ID,
        "version": CLIENT_VERSION,
        "platform": _platform.system().lower() or "unknown",
        "mode": client_mode or GATEWAY_CLIENT_MODE,
    }
    if display_name:
        client["displayName"] = display_name
    params: dict[str, Any] = {
        "minProtocol": MIN_PROTOCOL,
        "maxProtocol": MAX_PROTOCOL,
        "client": client,
        "role": "operator",
        "scopes": list(scopes) if scopes is not None else ["operator.read", "operator.write"],
        "caps": ["tool-events"],
        "commands": [],
        "permissions": {},
        "auth": auth,
        "locale": "en-US",
        "userAgent": f"{user_agent}/1.0",
    }
    if device:
        params["device"] = device
    return params
