"""OpenClaw device identity + registration for the Agentira daemon.

Pairs the daemon as its own OpenClaw device (with operator.write) via the
gateway connect handshake, then authenticates execution with the issued
device token. There is no device.pair.request RPC — pairing is initiated
by presenting a signed device object on connect.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import platform as _platform
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from agentira_cli.runtimes.openclaw_scopes import (
    WRITE_SCOPE_FALLBACK,
    default_requested_scopes,
)
from agentira_cli.state.paths import OPENCLAW_DEVICE_FILE, ensure_home

logger = logging.getLogger("agentira.runtime.openclaw_device")

DISPLAY_NAME = "agentira-daemon"
# Registration client identity — triggers silent local pairing on loopback.
# gateway-client/backend skips pairing and never issues a device token.
REG_CLIENT_ID = "cli"
REG_CLIENT_MODE = "cli"
# Execution client identity (canonical backend pair from gateway_connect).
EXEC_CLIENT_ID = "gateway-client"
EXEC_CLIENT_MODE = "backend"

_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


class GatewayRpcError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class RegistrationError(Exception):
    """Registration failed permanently (actionable message)."""


class RegistrationPendingError(RegistrationError):
    def __init__(self, request_id: str | None, device_id: str):
        self.request_id = request_id or ""
        self.device_id = device_id
        msg = (
            "OpenClaw device pairing is pending approval.\n"
            f"  device_id:  {device_id}\n"
            + (f"  request_id: {request_id}\n" if request_id else "")
            + "  Approve with: openclaw devices approve "
            + (request_id or "<requestId>")
            + "\n"
            "  Or approve in the OpenClaw Control UI, then re-run:\n"
            "    agentira daemon pair"
        )
        super().__init__(msg)


@dataclass
class DeviceIdentity:
    device_id: str
    public_key_pem: str
    private_key_pem: str
    device_token: str = ""
    scopes: list[str] = field(default_factory=list)
    gateway_url: str = ""
    display_name: str = DISPLAY_NAME
    registered_at_ms: int = 0
    version: int = 1

    def has_write_scope(self) -> bool:
        write = WRITE_SCOPE_FALLBACK
        try:
            from agentira_cli.runtimes.openclaw_scopes import discover_write_scope
            write = discover_write_scope()
        except Exception:
            pass
        return bool(self.device_token) and write in (self.scopes or [])


class GatewayTransport(Protocol):
    def connect_hello(self, *, url: str, connect_params: dict) -> dict: ...
    def request(
        self, *, url: str, connect_params: dict, method: str, params: dict
    ) -> dict: ...


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _normalize_meta(value: str | None) -> str:
    if not value:
        return ""
    trimmed = value.strip()
    if not trimmed:
        return ""
    return trimmed.lower()


def _raw_public_key_from_pem(public_key_pem: str) -> bytes:
    pub = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    if not isinstance(pub, Ed25519PublicKey):
        raise ValueError("expected Ed25519 public key")
    spki = pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if len(spki) == len(_ED25519_SPKI_PREFIX) + 32 and spki[: len(_ED25519_SPKI_PREFIX)] == _ED25519_SPKI_PREFIX:
        return spki[len(_ED25519_SPKI_PREFIX) :]
    return spki


def public_key_raw_b64url(public_key_pem: str) -> str:
    return _b64url(_raw_public_key_from_pem(public_key_pem))


def generate_identity(*, gateway_url: str = "") -> DeviceIdentity:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_key_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    raw = _raw_public_key_from_pem(public_key_pem)
    device_id = hashlib.sha256(raw).hexdigest()
    return DeviceIdentity(
        device_id=device_id,
        public_key_pem=public_key_pem,
        private_key_pem=private_key_pem,
        gateway_url=gateway_url,
        display_name=DISPLAY_NAME,
        scopes=default_requested_scopes(),
    )


def load_identity(path: Path | None = None) -> DeviceIdentity | None:
    path = path or OPENCLAW_DEVICE_FILE
    try:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        if not raw.get("device_id") or not raw.get("private_key_pem"):
            return None
        return DeviceIdentity(
            device_id=str(raw["device_id"]),
            public_key_pem=str(raw["public_key_pem"]),
            private_key_pem=str(raw["private_key_pem"]),
            device_token=str(raw.get("device_token") or ""),
            scopes=list(raw.get("scopes") or []),
            gateway_url=str(raw.get("gateway_url") or ""),
            display_name=str(raw.get("display_name") or DISPLAY_NAME),
            registered_at_ms=int(raw.get("registered_at_ms") or 0),
            version=int(raw.get("version") or 1),
        )
    except Exception as exc:
        logger.warning("failed to load openclaw device identity: %s", exc)
        return None


def save_identity(identity: DeviceIdentity, path: Path | None = None) -> None:
    path = path or OPENCLAW_DEVICE_FILE
    ensure_home()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(identity)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def build_device_auth_payload_v3(
    *,
    device_id: str,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    signed_at_ms: int,
    token: str,
    nonce: str,
    platform: str,
    device_family: str = "",
) -> str:
    return "|".join([
        "v3",
        device_id,
        client_id,
        client_mode,
        role,
        ",".join(scopes),
        str(signed_at_ms),
        token or "",
        nonce,
        _normalize_meta(platform),
        _normalize_meta(device_family),
    ])


def sign_device_payload(private_key_pem: str, payload: str) -> str:
    key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"), password=None
    )
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("expected Ed25519 private key")
    sig = key.sign(payload.encode("utf-8"))
    return _b64url(sig)


def build_device_connect_field(
    *,
    identity: DeviceIdentity,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    token: str,
    nonce: str,
    platform: str,
    device_family: str = "",
    signed_at_ms: int | None = None,
) -> dict:
    signed_at = signed_at_ms if signed_at_ms is not None else int(time.time() * 1000)
    payload = build_device_auth_payload_v3(
        device_id=identity.device_id,
        client_id=client_id,
        client_mode=client_mode,
        role=role,
        scopes=scopes,
        signed_at_ms=signed_at,
        token=token,
        nonce=nonce,
        platform=platform,
        device_family=device_family,
    )
    return {
        "id": identity.device_id,
        "publicKey": public_key_raw_b64url(identity.public_key_pem),
        "signature": sign_device_payload(identity.private_key_pem, payload),
        "signedAt": signed_at,
        "nonce": nonce,
    }


def _ws_base(gateway_url: str) -> str:
    return (
        gateway_url.rstrip("/")
        .replace("http://", "ws://")
        .replace("https://", "wss://")
    )


def _ws_url(gateway_url: str, token: str = "") -> str:
    base = _ws_base(gateway_url)
    if token:
        return f"{base}/?auth.token={token}"
    return base


class WebsocketTransport:
    """Thin WS transport matching OpenClaw challenge → connect → request."""

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout

    def _open(self, url: str):
        import websocket  # type: ignore

        # OpenClaw treats a browser Origin header as non-local and refuses
        # silent device pairing (NOT_PAIRED). websocket-client sends Origin
        # by default — suppress it for loopback daemon traffic.
        return websocket.create_connection(
            url, timeout=self.timeout, suppress_origin=True,
        )

    def _recv_json(self, ws) -> dict:
        raw = ws.recv()
        if not raw:
            return {}
        return json.loads(raw)

    def connect_hello(self, *, url: str, connect_params) -> dict:
        """Open WS, answer challenge, send connect, return hello payload.

        connect_params may be a dict or a callable(nonce) -> dict so the
        caller can sign the device field after the challenge.
        """
        ws = self._open(url)
        try:
            challenge = self._recv_json(ws)
            nonce = ""
            if challenge.get("type") == "event" and challenge.get("event") == "connect.challenge":
                nonce = (challenge.get("payload") or {}).get("nonce") or ""
            params = connect_params(nonce) if callable(connect_params) else connect_params
            ws.send(json.dumps({
                "type": "req",
                "id": "c1",
                "method": "connect",
                "params": params,
            }))
            hello = self._recv_json(ws)
            if not hello.get("ok"):
                err = hello.get("error") or {}
                if isinstance(err, dict):
                    raise GatewayRpcError(
                        str(err.get("code") or "ERROR"),
                        str(err.get("message") or hello),
                        err.get("details"),
                    )
                raise GatewayRpcError("ERROR", str(err or hello), None)
            return hello.get("payload") or {}
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def request(
        self, *, url: str, connect_params, method: str, params: dict
    ) -> dict:
        """Connect then call an RPC method on the same socket."""
        ws = self._open(url)
        try:
            challenge = self._recv_json(ws)
            nonce = ""
            if challenge.get("type") == "event" and challenge.get("event") == "connect.challenge":
                nonce = (challenge.get("payload") or {}).get("nonce") or ""
            cparams = connect_params(nonce) if callable(connect_params) else connect_params
            ws.send(json.dumps({
                "type": "req", "id": "c1", "method": "connect", "params": cparams,
            }))
            hello = self._recv_json(ws)
            if not hello.get("ok"):
                err = hello.get("error") or {}
                if isinstance(err, dict):
                    raise GatewayRpcError(
                        str(err.get("code") or "ERROR"),
                        str(err.get("message") or hello),
                        err.get("details"),
                    )
                raise GatewayRpcError("ERROR", str(err or hello), None)
            rid = "r1"
            ws.send(json.dumps({
                "type": "req", "id": rid, "method": method, "params": params,
            }))
            for _ in range(20):
                msg = self._recv_json(ws)
                if msg.get("type") == "res" and msg.get("id") == rid:
                    if not msg.get("ok"):
                        err = msg.get("error") or {}
                        if isinstance(err, dict):
                            raise GatewayRpcError(
                                str(err.get("code") or "ERROR"),
                                str(err.get("message") or msg),
                                err.get("details"),
                            )
                        raise GatewayRpcError("ERROR", str(err or msg), None)
                    return msg.get("payload") or {}
            raise GatewayRpcError("TIMEOUT", f"no response for {method}", None)
        finally:
            try:
                ws.close()
            except Exception:
                pass


def _build_reg_connect_params(
    identity: DeviceIdentity,
    *,
    gateway_token: str,
    scopes: list[str],
    nonce: str,
    client_id: str = REG_CLIENT_ID,
    client_mode: str = REG_CLIENT_MODE,
) -> dict:
    from agentira_cli.runtimes.gateway_connect import (
        CLIENT_VERSION,
        MAX_PROTOCOL,
        MIN_PROTOCOL,
    )

    plat = _platform.system().lower() or "unknown"
    device = build_device_connect_field(
        identity=identity,
        client_id=client_id,
        client_mode=client_mode,
        role="operator",
        scopes=scopes,
        token=gateway_token,
        nonce=nonce,
        platform=plat,
    )
    return {
        "minProtocol": MIN_PROTOCOL,
        "maxProtocol": MAX_PROTOCOL,
        "client": {
            "id": client_id,
            "version": CLIENT_VERSION,
            "platform": plat,
            "mode": client_mode,
            "displayName": identity.display_name or DISPLAY_NAME,
        },
        "role": "operator",
        "scopes": scopes,
        "caps": ["tool-events"],
        "commands": [],
        "permissions": {},
        "auth": {"token": gateway_token} if gateway_token else {},
        "device": device,
        "locale": "en-US",
        "userAgent": "agentira-daemon/1.0",
    }


def _build_admin_connect_params(
    identity: DeviceIdentity,
    *,
    gateway_token: str,
    nonce: str,
) -> dict:
    """Loopback backend connect requesting pairing scopes for self-approve."""
    scopes = [
        "operator.admin",
        "operator.read",
        "operator.write",
        "operator.approvals",
        "operator.pairing",
    ]
    return _build_reg_connect_params(
        identity,
        gateway_token=gateway_token,
        scopes=scopes,
        nonce=nonce,
        client_id=EXEC_CLIENT_ID,
        client_mode=EXEC_CLIENT_MODE,
    )


def _with_retries(fn, *, attempts: int = 3, label: str = "gateway"):
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except GatewayRpcError:
            raise
        except Exception as exc:
            last = exc
            if i + 1 < attempts:
                time.sleep(1.0 * (i + 1))
    raise RegistrationError(
        f"OpenClaw gateway unreachable ({label}): {last}. Is OpenClaw running?"
    )


def _self_approve(
    transport: GatewayTransport,
    *,
    gateway_url: str,
    gateway_token: str,
    request_id: str,
    admin_identity: DeviceIdentity,
) -> None:
    url = _ws_url(gateway_url, gateway_token)

    def connect_params(nonce: str) -> dict:
        return _build_admin_connect_params(
            admin_identity, gateway_token=gateway_token, nonce=nonce
        )

    transport.request(
        url=url,
        connect_params=connect_params,
        method="device.pair.approve",
        params={"requestId": request_id},
    )


def _cleanup_stale_agentira_devices(
    transport: GatewayTransport,
    *,
    gateway_url: str,
    gateway_token: str,
    identity: DeviceIdentity,
) -> None:
    """Remove prior agentira-daemon entries that are not our current device.

    Uses a throwaway loopback backend identity so we can request
    operator.pairing without triggering a scope-upgrade on the daemon device.
    """
    url = _ws_url(gateway_url, gateway_token)
    our_pub = public_key_raw_b64url(identity.public_key_pem)
    admin = generate_identity(gateway_url=gateway_url)

    def connect_params(nonce: str) -> dict:
        return _build_admin_connect_params(
            admin, gateway_token=gateway_token, nonce=nonce
        )

    try:
        listing = transport.request(
            url=url,
            connect_params=connect_params,
            method="device.pair.list",
            params={},
        )
    except Exception as exc:
        logger.debug("device.pair.list for cleanup failed: %s", exc)
        return

    paired = listing.get("paired") or []
    for entry in paired:
        if not isinstance(entry, dict):
            continue
        did = str(entry.get("deviceId") or "")
        if not did or did == identity.device_id:
            continue
        label = str(entry.get("displayName") or "")
        pub = str(entry.get("publicKey") or "")
        # Only our label, or our public key under a different id (shouldn't happen).
        if label != DISPLAY_NAME and pub != our_pub:
            continue
        try:
            transport.request(
                url=url,
                connect_params=connect_params,
                method="device.pair.remove",
                params={"deviceId": did},
            )
            logger.info("removed stale OpenClaw device %s (%s)", did[:12], label)
        except Exception as exc:
            logger.debug("device.pair.remove %s failed: %s", did[:12], exc)


def ensure_registered(
    *,
    gateway_url: str,
    gateway_token: str,
    identity_path: Path | None = None,
    transport: GatewayTransport | None = None,
    force: bool = False,
) -> DeviceIdentity:
    """Idempotent: return a write-scoped device identity with device_token.

    Fast path: cached token + write scope.
    A1: registration connect (cli/cli) silently pairs on loopback.
    A2: NOT_PAIRED → self-approve with pairing scopes; else raise pending.
    """
    if not gateway_url:
        raise RegistrationError("missing OpenClaw gateway_url")
    if not gateway_token:
        raise RegistrationError(
            "missing OpenClaw gateway token (gateway.auth.token in openclaw.json)"
        )

    path = identity_path or OPENCLAW_DEVICE_FILE
    transport = transport or WebsocketTransport()
    scopes = default_requested_scopes()
    write_scope = next((s for s in scopes if s.endswith(".write")), WRITE_SCOPE_FALLBACK)

    identity = load_identity(path)
    if identity is None:
        identity = generate_identity(gateway_url=gateway_url)
        save_identity(identity, path)
    else:
        identity.gateway_url = gateway_url or identity.gateway_url
        if not identity.scopes:
            identity.scopes = list(scopes)

    if not force and identity.has_write_scope():
        return identity

    url = _ws_url(gateway_url, gateway_token)

    def reg_params(nonce: str) -> dict:
        return _build_reg_connect_params(
            identity, gateway_token=gateway_token, scopes=scopes, nonce=nonce
        )

    def do_register() -> dict:
        return transport.connect_hello(url=url, connect_params=reg_params)

    try:
        hello = _with_retries(do_register, label=gateway_url)
    except GatewayRpcError as e:
        if str(e.code) not in ("NOT_PAIRED", "not_paired") and "NOT_PAIRED" not in str(e.message):
            # Some gateways put pairing in message only
            if "pair" not in str(e.message).lower() and "not paired" not in str(e.message).lower():
                raise RegistrationError(
                    f"OpenClaw connect failed: {e.code}: {e.message}"
                ) from e
        request_id = None
        if isinstance(e.details, dict):
            request_id = e.details.get("requestId") or e.details.get("request_id")
        # A1 explicit self-approve using shared gateway token + pairing scopes
        if request_id:
            try:
                admin = generate_identity(gateway_url=gateway_url)
                _self_approve(
                    transport,
                    gateway_url=gateway_url,
                    gateway_token=gateway_token,
                    request_id=str(request_id),
                    admin_identity=admin,
                )
                hello = _with_retries(do_register, label=gateway_url)
            except GatewayRpcError as approve_err:
                logger.info(
                    "self-approve denied (%s); leaving pending",
                    approve_err.message,
                )
                raise RegistrationPendingError(str(request_id), identity.device_id) from approve_err
            except RegistrationPendingError:
                raise
            except Exception as approve_err:
                logger.info("self-approve failed: %s", approve_err)
                raise RegistrationPendingError(str(request_id), identity.device_id) from approve_err
        else:
            raise RegistrationPendingError(None, identity.device_id) from e

    auth = hello.get("auth") or {}
    token = auth.get("deviceToken") or ""
    granted = list(auth.get("scopes") or [])
    if not token:
        raise RegistrationError(
            "OpenClaw pairing completed but no device token was issued. "
            "Re-run: agentira daemon pair"
        )
    if write_scope not in granted and WRITE_SCOPE_FALLBACK not in granted:
        raise RegistrationError(
            "OpenClaw device paired but missing write scope "
            f"(got {granted!r}). Re-run: agentira daemon pair. "
            "Check: openclaw devices list"
        )

    identity.device_token = str(token)
    identity.scopes = granted
    identity.gateway_url = gateway_url
    identity.registered_at_ms = int(time.time() * 1000)
    save_identity(identity, path)

    try:
        _cleanup_stale_agentira_devices(
            transport,
            gateway_url=gateway_url,
            gateway_token=gateway_token,
            identity=identity,
        )
    except Exception as exc:
        logger.debug("stale device cleanup skipped: %s", exc)

    return identity
