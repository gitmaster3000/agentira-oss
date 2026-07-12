"""Unit tests for OpenClaw device identity, signing, and ensure_registered."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentira_cli.runtimes.openclaw_device import (
    DISPLAY_NAME,
    DeviceIdentity,
    GatewayRpcError,
    RegistrationError,
    RegistrationPendingError,
    build_device_auth_payload_v3,
    build_device_connect_field,
    ensure_registered,
    generate_identity,
    load_identity,
    public_key_raw_b64url,
    save_identity,
    sign_device_payload,
)


class FakeTransport:
    def __init__(self, scripts: list):
        self.scripts = list(scripts)
        self.calls: list = []

    def connect_hello(self, *, url: str, connect_params):
        nonce = "test-nonce"
        params = connect_params(nonce) if callable(connect_params) else connect_params
        self.calls.append(("connect", url, params))
        if not self.scripts:
            raise RuntimeError("FakeTransport: no scripts left for connect_hello")
        item = self.scripts.pop(0)
        if item.get("ok") is False:
            err = item.get("error") or {}
            raise GatewayRpcError(
                str(err.get("code") or "ERROR"),
                str(err.get("message") or "error"),
                err.get("details"),
            )
        return item.get("payload") or {}

    def request(self, *, url: str, connect_params, method: str, params: dict):
        cparams = connect_params("test-nonce") if callable(connect_params) else connect_params
        self.calls.append(("req", method, params, cparams))
        if not self.scripts:
            raise RuntimeError(f"FakeTransport: no scripts left for {method}")
        item = self.scripts.pop(0)
        if item.get("ok") is False:
            err = item.get("error") or {}
            raise GatewayRpcError(
                str(err.get("code") or "ERROR"),
                str(err.get("message") or "error"),
                err.get("details"),
            )
        return item.get("payload") or {}


def test_generate_and_persist_roundtrip(tmp_path: Path):
    path = tmp_path / "openclaw-device.json"
    ident = generate_identity(gateway_url="http://127.0.0.1:18789")
    assert ident.device_id
    assert "BEGIN PRIVATE KEY" in ident.private_key_pem
    save_identity(ident, path)
    assert path.stat().st_mode & 0o777 == 0o600
    loaded = load_identity(path)
    assert loaded is not None
    assert loaded.device_id == ident.device_id
    assert loaded.private_key_pem == ident.private_key_pem


def test_v3_payload_shape_and_signature():
    ident = generate_identity(gateway_url="http://127.0.0.1:18789")
    payload = build_device_auth_payload_v3(
        device_id=ident.device_id,
        client_id="cli",
        client_mode="cli",
        role="operator",
        scopes=["operator.read", "operator.write"],
        signed_at_ms=1_700_000_000_000,
        token="gw-token",
        nonce="nonce-1",
        platform="Darwin",
        device_family="",
    )
    assert payload.startswith("v3|")
    parts = payload.split("|")
    assert parts[0] == "v3"
    assert parts[1] == ident.device_id
    assert parts[5] == "operator.read,operator.write"
    assert parts[9] == "darwin"
    sig = sign_device_payload(ident.private_key_pem, payload)
    assert isinstance(sig, str) and len(sig) > 20
    assert "=" not in sig


def test_build_device_connect_field_keys():
    ident = generate_identity(gateway_url="http://127.0.0.1:18789")
    dev = build_device_connect_field(
        identity=ident,
        client_id="cli",
        client_mode="cli",
        role="operator",
        scopes=["operator.read", "operator.write"],
        token="t",
        nonce="n",
        platform="darwin",
    )
    assert set(dev) == {"id", "publicKey", "signature", "signedAt", "nonce"}
    assert dev["id"] == ident.device_id
    assert dev["nonce"] == "n"
    assert public_key_raw_b64url(ident.public_key_pem) == dev["publicKey"]


def test_fast_path_no_rpc_when_write_token_cached(tmp_path: Path):
    path = tmp_path / "openclaw-device.json"
    ident = generate_identity(gateway_url="http://127.0.0.1:18789")
    ident.device_token = "cached-tok"
    ident.scopes = ["operator.read", "operator.write"]
    save_identity(ident, path)
    transport = FakeTransport([])
    out = ensure_registered(
        gateway_url="http://127.0.0.1:18789",
        gateway_token="gw",
        identity_path=path,
        transport=transport,
    )
    assert out.device_token == "cached-tok"
    assert transport.calls == []


def test_a1_silent_pair_stores_token(tmp_path: Path):
    path = tmp_path / "openclaw-device.json"
    transport = FakeTransport([
        {
            "ok": True,
            "payload": {
                "type": "hello-ok",
                "auth": {
                    "role": "operator",
                    "scopes": ["operator.read", "operator.write"],
                    "deviceToken": "dev-tok-1",
                    "issuedAtMs": 1,
                },
            },
        },
        {
            "ok": True,
            "payload": {
                "pending": [],
                "paired": [
                    {
                        "deviceId": "stale",
                        "displayName": DISPLAY_NAME,
                        "publicKey": "other",
                    },
                    {
                        "deviceId": "ui",
                        "displayName": "Control UI",
                        "clientId": "openclaw-control-ui",
                    },
                ],
            },
        },
        {"ok": True, "payload": {"deviceId": "stale"}},
    ])
    ident = ensure_registered(
        gateway_url="http://127.0.0.1:18789",
        gateway_token="gw",
        identity_path=path,
        transport=transport,
    )
    assert ident.device_token == "dev-tok-1"
    assert "operator.write" in ident.scopes
    loaded = load_identity(path)
    assert loaded is not None and loaded.device_token == "dev-tok-1"
    remove_calls = [c for c in transport.calls if c[0] == "req" and c[1] == "device.pair.remove"]
    assert remove_calls and remove_calls[0][2]["deviceId"] == "stale"
    # never touch control-ui
    removed_ids = {c[2]["deviceId"] for c in remove_calls}
    assert "ui" not in removed_ids


def test_a2_self_approve_then_token(tmp_path: Path):
    path = tmp_path / "openclaw-device.json"
    transport = FakeTransport([
        {
            "ok": False,
            "error": {
                "code": "NOT_PAIRED",
                "message": "pairing required",
                "details": {"requestId": "req-1", "reason": "not-paired"},
            },
        },
        # approve
        {"ok": True, "payload": {"requestId": "req-1", "device": {"deviceId": "x"}}},
        # re-register
        {
            "ok": True,
            "payload": {
                "auth": {
                    "scopes": ["operator.read", "operator.write"],
                    "deviceToken": "after-approve",
                },
            },
        },
        # cleanup list
        {"ok": True, "payload": {"pending": [], "paired": []}},
    ])
    ident = ensure_registered(
        gateway_url="http://127.0.0.1:18789",
        gateway_token="gw",
        identity_path=path,
        transport=transport,
    )
    assert ident.device_token == "after-approve"
    approve_calls = [c for c in transport.calls if c[0] == "req" and c[1] == "device.pair.approve"]
    assert approve_calls and approve_calls[0][2] == {"requestId": "req-1"}


def test_self_approve_denied_raises_pending(tmp_path: Path):
    path = tmp_path / "openclaw-device.json"
    transport = FakeTransport([
        {
            "ok": False,
            "error": {
                "code": "NOT_PAIRED",
                "message": "pairing required",
                "details": {"requestId": "req-2"},
            },
        },
        {
            "ok": False,
            "error": {
                "code": "INVALID_REQUEST",
                "message": "missing scope: operator.pairing",
            },
        },
    ])
    with pytest.raises(RegistrationPendingError) as ei:
        ensure_registered(
            gateway_url="http://127.0.0.1:18789",
            gateway_token="gw",
            identity_path=path,
            transport=transport,
        )
    assert ei.value.request_id == "req-2"
    assert "openclaw devices approve" in str(ei.value)


def test_missing_write_after_pair_errors(tmp_path: Path):
    path = tmp_path / "openclaw-device.json"
    transport = FakeTransport([
        {
            "ok": True,
            "payload": {
                "auth": {
                    "scopes": ["operator.read"],
                    "deviceToken": "tok-no-write",
                },
            },
        },
    ])
    with pytest.raises(RegistrationError) as ei:
        ensure_registered(
            gateway_url="http://127.0.0.1:18789",
            gateway_token="gw",
            identity_path=path,
            transport=transport,
        )
    assert "write" in str(ei.value).lower()


def test_has_write_scope():
    ident = DeviceIdentity(
        device_id="d",
        public_key_pem="p",
        private_key_pem="k",
        device_token="t",
        scopes=["operator.read", "operator.write"],
    )
    assert ident.has_write_scope()
    ident.scopes = ["operator.read"]
    assert not ident.has_write_scope()
    ident.scopes = ["operator.read", "operator.write"]
    ident.device_token = ""
    assert not ident.has_write_scope()
