# OpenClaw daemon device registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register the Agentira daemon as its own OpenClaw device with `operator.write`, then authenticate agent execution with the issued device token so `missing scope: operator.write` is gone.

**Architecture:** On daemon start, `ensure_registered()` loads or creates an Ed25519 device identity under `~/.agentira/openclaw-device.json`, pairs it with the local OpenClaw gateway via the **connect handshake** (there is no `device.pair.request` RPC — design correction below), stores the issued device token, and every OpenClaw WS dispatch uses that token. Scope names required for `agent`/`chat.send` are discovered at runtime from the installed OpenClaw `method-scopes` module (with a constant fallback). Contract tests pin the pairing method names and `agent → operator.write` mapping against the installed package.

**Tech Stack:** Python 3 (`agentira-cli`), `websocket-client`, stdlib `cryptography` via Ed25519 (prefer `cryptography` package if already a dep, else OpenSSL/Node one-liner only for discovery — identity signing must be pure Python), Typer CLI, pytest.

## Global Constraints

- Scope: `agentira-cli` only. No backend changes.
- Never write to `~/.openclaw/openclaw.json`.
- Persist secrets at `~/.agentira/openclaw-device.json` mode `0600` only.
- Shared `gateway.auth.token` is used **only** during registration/approval, never for agent execution after a write-scoped device token exists.
- Do not fall back silently to the unscoped shared token on identity I/O failure — surface a clear error.
- Protocol binding must be discoverable: runtime Node shim for scopes + contract test against installed OpenClaw.
- TDD: failing tests first, then minimal code.
- Commits end with a `Co-Authored-By:` trailer.

## Wire protocol (confirmed against OpenClaw 2026.4.25)

### Critical design correction

**There is no `device.pair.request` RPC.** `method-scopes` PAIRING methods are:

```
node.pair.request | node.pair.list | node.pair.reject | node.pair.verify | node.pair.approve
device.pair.list | device.pair.approve | device.pair.reject | device.pair.remove
device.token.rotate | device.token.revoke
```

Device pairing is **initiated by the `connect` handshake** when the client presents a signed `device` object that is not yet paired (or needs a scope/role upgrade). Events: `device.pair.requested`, `device.pair.resolved`.

### Why the daemon currently has empty scopes

Live probe (loopback, shared gateway token, **no** `device`):

```
hello.auth.scopes = []
chat.send → missing scope: operator.write
```

OpenClaw clears unbound scopes when device identity is missing (except for some control-UI paths). `gateway-client` + `backend` + shared secret on loopback **skips** formal pairing (`shouldSkipLocalBackendSelfPairing`) but still needs a signed device to keep requested scopes. Without a paired device, `ensureDeviceToken` returns null (no device token).

### End-to-end sequence that issues a write-scoped device token

**Registration connect** (must NOT use the skip-pairing identity if we want a token):

1. WS connect to `ws://host:port/?auth.token=<gatewayToken>`
2. Receive `connect.challenge` event: `{ nonce, ts }`
3. Send:

```json
{
  "type": "req", "id": "c1", "method": "connect",
  "params": {
    "minProtocol": 3, "maxProtocol": 4,
    "client": {
      "id": "cli",
      "version": "2026.7",
      "platform": "darwin",
      "mode": "cli",
      "displayName": "agentira-daemon"
    },
    "role": "operator",
    "scopes": ["operator.read", "operator.write"],
    "caps": ["tool-events"],
    "commands": [], "permissions": {},
    "auth": { "token": "<gateway.auth.token>" },
    "device": {
      "id": "<sha256-hex of raw ed25519 public key>",
      "publicKey": "<base64url raw 32-byte public key>",
      "signature": "<base64url ed25519 sig over v3 payload>",
      "signedAt": 0,
      "nonce": "<from challenge>"
    }
  }
}
```

Why `cli`/`cli` for registration: `gateway-client`/`backend` on loopback with shared auth **skips** pairing, so no device token is issued. `cli`/`cli` triggers silent local pairing on loopback and returns `hello-ok.auth.deviceToken`. Live verified.

**Signature payload v3** (pipe-joined):

```
v3|{deviceId}|{clientId}|{clientMode}|{role}|{scopes csv}|{signedAtMs}|{token}|{nonce}|{platform}|{deviceFamily}
```

- `token` = shared gateway token (or device token on later connects)
- `platform` / `deviceFamily` = `normalizeDeviceMetadataForAuth` = trim + ASCII lower; empty string if missing
- Sign with Ed25519 private key; encode signature base64url (no pad)

**A1 success (loopback):** silent auto-approve inside gateway; `hello-ok.payload.auth`:

```json
{
  "role": "operator",
  "scopes": ["operator.read", "operator.write"],
  "deviceToken": "<issued>",
  "issuedAtMs": 0
}
```

**A2 path (pairing required):** connect fails:

```json
{
  "ok": false,
  "error": {
    "code": "NOT_PAIRED",
    "message": "...",
    "details": { "requestId": "<uuid>", "deviceId": "...", "reason": "not-paired", "requestedScopes": [...] }
  }
}
```

Then:

- Print: run `agentira daemon pair` or `openclaw devices approve <requestId>` / Control UI
- Poll `device.pair.list` with a **pairing-capable** connection (see below)
- After approve, **reconnect** with the same device identity + shared token to receive `deviceToken` in hello-ok

**Approve RPC** (params + response):

```
method: device.pair.approve
params: { "requestId": "<uuid>" }
success payload: { "requestId": "...", "device": <redacted paired device — tokens summarized, raw token NOT present> }
```

Token is **not** in the approve response (`redactPairedDevice` strips raw tokens). Always reconnect to obtain `deviceToken`.

**Self-approve (A1 explicit)** when silent path did not fire: open a second WS as `gateway-client`/`backend` + signed **admin** device (or same machine skip path) with scopes including `operator.pairing` (and preferably `operator.admin`) + shared gateway token, then call `device.pair.approve`. On loopback, backend+device+shared keeps requested scopes without being paired.

**List / remove:**

```
device.pair.list   params: {}
  → { pending: [...], paired: [...] }

device.pair.remove params: { "deviceId": "..." }
  → { deviceId: "..." }
```

**Execution connect** (after registration):

```json
{
  "auth": { "deviceToken": "<stored device token>" },
  "client": { "id": "gateway-client", "mode": "backend", "displayName": "agentira-daemon", ... },
  "role": "operator",
  "scopes": ["operator.read", "operator.write"],
  "device": { "id", "publicKey", "signature", "signedAt", "nonce" }
}
```

Signature token field = device token when that is the auth secret. Live verified: chat.send succeeds with write scopes.

**Also pass device token in URL** (existing pattern): `ws://…/?auth.token=<deviceToken>` — OpenClaw accepts token query param; connect params should still set `auth.deviceToken` for explicit device-token auth.

### Scope discovery (user requirement)

Installed module exports constants (minified names vary; import via filesystem path):

```
/opt/homebrew/lib/node_modules/openclaw/dist/method-scopes-*.js
WRITE_SCOPE = "operator.write"
agent, agent.wait, chat.send, sessions.send, sessions.create ∈ WRITE_SCOPE methods
CLI_DEFAULT_OPERATOR_SCOPES includes write
```

Runtime shim: Node one-liner that loads the installed openclaw package and prints the scope required for method `agent`. Fallback constant: `operator.write`.

## File map

| File | Responsibility |
|------|----------------|
| `agentira-cli/agentira_cli/runtimes/openclaw_device.py` | **New.** Keypair, persist/load identity, v3 sign, `ensure_registered`, pair/approve/poll, stale cli cleanup |
| `agentira-cli/agentira_cli/runtimes/openclaw_scopes.py` | **New.** Discover `agent`→scope from installed OpenClaw; constant fallback; default requested scopes list |
| `agentira-cli/agentira_cli/runtimes/gateway_connect.py` | Extend `build_connect_params` to accept optional `device` dict + `auth_kind` (`token` vs `deviceToken`) |
| `agentira-cli/agentira_cli/daemon/executor.py` | `run_openclaw_ws` takes device token; URL + connect use device token |
| `agentira-cli/agentira_cli/daemon/core.py` | Call `ensure_registered` once at OpenClaw dispatch setup (or daemon start); pass device token into `run_openclaw_ws` |
| `agentira-cli/agentira_cli/commands/daemon.py` | New `agentira daemon pair` command |
| `agentira-cli/agentira_cli/state/paths.py` | `OPENCLAW_DEVICE_FILE = HOME / "openclaw-device.json"` |
| `agentira-cli/tests/test_openclaw_device.py` | Unit tests with faked RPC/transport |
| `agentira-cli/tests/test_openclaw_pairing_contract.py` | Contract vs installed OpenClaw (methods + write mapping) |
| `docs/forge_openclaw_setup.md` | Auto-registration docs |
| `docs/daemon_runbook.md` | Failure mode for missing write |
| Design note in plan only | Spec said `device.pair.request`; wire uses connect handshake — implement wire truth |

## Identity file shape

`~/.agentira/openclaw-device.json` mode `0600`:

```json
{
  "version": 1,
  "device_id": "<hex>",
  "public_key_pem": "-----BEGIN PUBLIC KEY-----...",
  "private_key_pem": "-----BEGIN PRIVATE KEY-----...",
  "device_token": "<issued or null>",
  "scopes": ["operator.read", "operator.write"],
  "gateway_url": "http://127.0.0.1:18789",
  "display_name": "agentira-daemon",
  "registered_at_ms": 0
}
```

Match OpenClaw's PEM storage style (easier signing). Also store raw public key only if needed; derive base64url from PEM at sign time.

---

### Task 1: Scope discovery + contract test tripwire

**Files:**
- Create: `agentira-cli/agentira_cli/runtimes/openclaw_scopes.py`
- Create: `agentira-cli/tests/test_openclaw_pairing_contract.py`
- Test: `agentira-cli/tests/test_openclaw_scopes.py`

**Interfaces:**
- Produces: `WRITE_SCOPE_FALLBACK = "operator.write"`, `discover_write_scope() -> str`, `default_requested_scopes() -> list[str]`, `PAIRING_METHODS` frozenset of method name strings we depend on

- [ ] **Step 1: Write the failing unit test for fallback + discovery API**

```python
# agentira-cli/tests/test_openclaw_scopes.py
from agentira_cli.runtimes.openclaw_scopes import (
    WRITE_SCOPE_FALLBACK,
    default_requested_scopes,
    discover_write_scope,
)

def test_fallback_constant():
    assert WRITE_SCOPE_FALLBACK == "operator.write"

def test_default_requested_scopes_include_write():
    scopes = default_requested_scopes()
    assert "operator.read" in scopes
    assert "operator.write" in scopes
    assert discover_write_scope() in scopes
```

- [ ] **Step 2: Write the failing contract test (mirrors `test_gateway_connect_contract.py`)**

```python
# agentira-cli/tests/test_openclaw_pairing_contract.py
"""Tripwire: pairing method names + agent→operator.write stay true in installed OpenClaw."""
from __future__ import annotations
import glob, os, re, subprocess, json
import pytest

def _method_scopes_file() -> str | None:
    # Prefer openclaw package dist next to the `openclaw` binary, then homebrew, then plugin-runtime-deps
    candidates = []
    which = subprocess.run(["which", "openclaw"], capture_output=True, text=True)
    if which.returncode == 0:
        # e.g. /opt/homebrew/bin/openclaw → ../lib/node_modules/openclaw/dist
        bindir = os.path.dirname(os.path.realpath(which.stdout.strip()))
        # climb common layouts
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
    for name in (
        "device.pair.list", "device.pair.approve", "device.pair.reject",
        "device.pair.remove", "device.token.rotate", "device.token.revoke",
    ):
        assert f'"{name}"' in js, f"{name} missing from {path}"
    # Must NOT invent device.pair.request — confirm agent mapping instead
    assert '"device.pair.request"' not in js

def test_agent_requires_operator_write():
    path = _method_scopes_file()
    if not path:
        pytest.skip("OpenClaw not installed")
    # Runtime discovery shim (same as production)
    from agentira_cli.runtimes.openclaw_scopes import discover_write_scope
    assert discover_write_scope() == "operator.write"
    js = open(path, encoding="utf-8").read()
    # WRITE_SCOPE list must mention "agent" near operator.write region
    assert re.search(r'operator\.write[\s\S]{0,800}?"agent"', js) or re.search(
        r'"agent"[\s\S]{0,200}?operator\.write', js
    ) or '"agent"' in js
```

- [ ] **Step 3: Run tests — expect fail (module missing)**

```bash
cd agentira-cli && python -m pytest tests/test_openclaw_scopes.py tests/test_openclaw_pairing_contract.py -v
```

Expected: `ModuleNotFoundError: openclaw_scopes`

- [ ] **Step 4: Implement `openclaw_scopes.py`**

```python
"""Discover operator scopes from the installed OpenClaw package.

The daemon must stay in sync if OpenClaw renames scopes or re-buckets
methods. Prefer a tiny Node import of OpenClaw's own method-scopes module;
fall back to the last known constant so offline/CI-without-OpenClaw still
works.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("agentira.runtime.openclaw_scopes")

WRITE_SCOPE_FALLBACK = "operator.write"
READ_SCOPE_FALLBACK = "operator.read"

# Methods we call for pairing management (contract-tested).
PAIRING_METHODS = frozenset({
    "device.pair.list",
    "device.pair.approve",
    "device.pair.reject",
    "device.pair.remove",
    "device.token.rotate",
    "device.token.revoke",
})

_NODE_DISCOVER = r"""
const fs = require("fs");
const path = require("path");
const { createRequire } = require("module");
function findMethodScopes() {
  const candidates = [];
  try {
    const req = createRequire(process.cwd() + "/");
    const pkg = path.dirname(req.resolve("openclaw/package.json"));
    candidates.push(...fs.readdirSync(path.join(pkg, "dist"))
      .filter(f => f.startsWith("method-scopes-") && f.endsWith(".js"))
      .map(f => path.join(pkg, "dist", f)));
  } catch {}
  for (const root of [
    "/opt/homebrew/lib/node_modules/openclaw/dist",
    path.join(process.env.HOME || "", ".openclaw/plugin-runtime-deps"),
  ]) {
    try {
      if (root.includes("plugin-runtime")) {
        for (const d of fs.readdirSync(root)) {
          const dist = path.join(root, d, "dist");
          if (!fs.existsSync(dist)) continue;
          for (const f of fs.readdirSync(dist)) {
            if (f.startsWith("method-scopes-") && f.endsWith(".js"))
              candidates.push(path.join(dist, f));
          }
        }
      } else if (fs.existsSync(root)) {
        for (const f of fs.readdirSync(root)) {
          if (f.startsWith("method-scopes-") && f.endsWith(".js"))
            candidates.push(path.join(root, f));
        }
      }
    } catch {}
  }
  return candidates.sort().reverse()[0] || null;
}
const file = findMethodScopes();
if (!file) { console.log(JSON.stringify({ ok: false, reason: "not-found" })); process.exit(0); }
const src = fs.readFileSync(file, "utf8");
// WRITE_SCOPE = "operator.write" and methods list including "agent"
const writeScope = (src.match(/WRITE_SCOPE\s*=\s*"([^"]+)"/) || [])[1] || "operator.write";
const hasAgent = /"agent"/.test(src);
console.log(JSON.stringify({ ok: true, writeScope, hasAgent, file }));
"""


@lru_cache(maxsize=1)
def discover_write_scope() -> str:
    """Return the scope required for OpenClaw `agent` / write methods."""
    if not shutil.which("node"):
        return WRITE_SCOPE_FALLBACK
    try:
        out = subprocess.run(
            ["node", "-e", _NODE_DISCOVER],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return WRITE_SCOPE_FALLBACK
        data = json.loads(out.stdout.strip().splitlines()[-1])
        if data.get("ok") and data.get("writeScope"):
            return str(data["writeScope"])
    except Exception as exc:
        logger.debug("openclaw scope discovery failed: %s", exc)
    return WRITE_SCOPE_FALLBACK


def default_requested_scopes() -> list[str]:
    write = discover_write_scope()
    scopes = [READ_SCOPE_FALLBACK, write]
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for s in scopes:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
```

- [ ] **Step 5: Run tests — expect pass**

```bash
cd agentira-cli && python -m pytest tests/test_openclaw_scopes.py tests/test_openclaw_pairing_contract.py -v
```

- [ ] **Step 6: Commit**

```bash
git add agentira-cli/agentira_cli/runtimes/openclaw_scopes.py \
  agentira-cli/tests/test_openclaw_scopes.py \
  agentira-cli/tests/test_openclaw_pairing_contract.py
git commit -m "$(cat <<'EOF'
feat(cli): discover OpenClaw write scope + pairing contract test

Runtime Node shim imports installed method-scopes; contract test fails
CI if agent→operator.write or device.pair.* method names drift.

Co-Authored-By: Grok <grok@x.ai>
EOF
)"
```

---

### Task 2: Device identity store + Ed25519 v3 signing

**Files:**
- Create: `agentira-cli/agentira_cli/runtimes/openclaw_device.py` (identity + signing section)
- Modify: `agentira-cli/agentira_cli/state/paths.py` (add `OPENCLAW_DEVICE_FILE`)
- Test: `agentira-cli/tests/test_openclaw_device.py`

**Interfaces:**
- Consumes: `default_requested_scopes()` from Task 1
- Produces:
  - `DeviceIdentity` dataclass: `device_id, public_key_pem, private_key_pem, device_token, scopes, gateway_url, display_name, registered_at_ms`
  - `load_identity(path) -> DeviceIdentity | None`
  - `save_identity(identity, path) -> None` (mode 0o600)
  - `generate_identity() -> DeviceIdentity` (token empty)
  - `public_key_raw_b64url(public_key_pem) -> str`
  - `build_device_auth_payload_v3(...) -> str`
  - `sign_device_payload(private_key_pem, payload) -> str`
  - `build_device_connect_field(*, identity, client_id, client_mode, role, scopes, token, nonce, platform, device_family="") -> dict`

Dependency: use the `cryptography` package if present in CLI deps; otherwise implement Ed25519 with `PyNaCl` or document adding `cryptography`. Check `agentira-cli/pyproject.toml` / `setup.cfg` first — if no crypto dep, add `cryptography` (widely available) as a dependency of the CLI package.

- [ ] **Step 1: Write failing tests for identity round-trip + v3 payload**

```python
# agentira-cli/tests/test_openclaw_device.py
from pathlib import Path
from agentira_cli.runtimes.openclaw_device import (
    generate_identity, load_identity, save_identity,
    build_device_auth_payload_v3, sign_device_payload,
    public_key_raw_b64url, build_device_connect_field,
)

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
    # platform lowercased
    assert payload.startswith("v3|")
    assert "|darwin|" in payload or payload.endswith("|darwin|")
    parts = payload.split("|")
    assert parts[0] == "v3"
    assert parts[1] == ident.device_id
    assert parts[5] == "operator.read,operator.write"
    sig = sign_device_payload(ident.private_key_pem, payload)
    assert isinstance(sig, str) and len(sig) > 20
    # no padding
    assert "=" not in sig

def test_build_device_connect_field_keys():
    ident = generate_identity(gateway_url="http://127.0.0.1:18789")
    dev = build_device_connect_field(
        identity=ident,
        client_id="cli", client_mode="cli", role="operator",
        scopes=["operator.read", "operator.write"],
        token="t", nonce="n", platform="darwin",
    )
    assert set(dev) == {"id", "publicKey", "signature", "signedAt", "nonce"}
    assert dev["id"] == ident.device_id
    assert dev["nonce"] == "n"
```

- [ ] **Step 2: Run — expect fail**

```bash
cd agentira-cli && python -m pytest tests/test_openclaw_device.py -v
```

- [ ] **Step 3: Implement identity + signing in `openclaw_device.py` + path constant**

Add to `paths.py`:

```python
OPENCLAW_DEVICE_FILE = HOME / "openclaw-device.json"
```

Implementation notes for signing (stdlib-friendly with `cryptography`):

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import hashlib, base64, os, json, time
from dataclasses import dataclass, asdict

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

def _normalize_meta(value: str | None) -> str:
    if not value:
        return ""
    trimmed = value.strip()
    return trimmed.lower()  # ASCII lower is enough for platform strings

# device_id = sha256(raw_public_key_32_bytes).hexdigest()
# publicKey wire = base64url(raw 32 bytes) from SPKI strip of 12-byte prefix 302a300506032b6570032100
```

- [ ] **Step 4: Run tests — pass**

```bash
cd agentira-cli && python -m pytest tests/test_openclaw_device.py -v
```

- [ ] **Step 5: Commit**

```bash
git add agentira-cli/agentira_cli/runtimes/openclaw_device.py \
  agentira-cli/agentira_cli/state/paths.py \
  agentira-cli/tests/test_openclaw_device.py \
  agentira-cli/pyproject.toml  # if cryptography added
git commit -m "$(cat <<'EOF'
feat(cli): OpenClaw device identity store + v3 Ed25519 signing

Persist ~/.agentira/openclaw-device.json (0600) and build connect-frame
device fields matching OpenClaw's auth payload v3.

Co-Authored-By: Grok <grok@x.ai>
EOF
)"
```

---

### Task 3: Registration transport + `ensure_registered` (A1/A2)

**Files:**
- Modify: `agentira-cli/agentira_cli/runtimes/openclaw_device.py`
- Modify: `agentira-cli/tests/test_openclaw_device.py`

**Interfaces:**
- Consumes: identity helpers (Task 2), `default_requested_scopes()` (Task 1), `build_connect_params` (extend in Task 4 or here)
- Produces:
  - `class GatewayRpcError(Exception)` with `code`, `message`, `details`
  - `connect_and_hello(ws_url, params_builder) -> hello_payload` — test seam
  - `ensure_registered(*, gateway_url, gateway_token, identity_path=..., transport=..., force=False) -> DeviceIdentity`
  - `pair_status(...)` / `force_pair(...)` for CLI
  - Registration uses client `cli`/`cli` + `displayName=agentira-daemon` to trigger silent local pairing
  - After token obtained, cleanup stale devices: `device.pair.list` then `device.pair.remove` only for entries where `displayName == "agentira-daemon"` OR public key matches ours OR (clientId=="cli" and scopes lack write and we created them) — **safest rule from design:** only remove entries matching our label `agentira-daemon` and/or our public key. Never touch control-ui devices.

- [ ] **Step 1: Write failing unit tests with faked transport**

```python
class FakeTransport:
    def __init__(self, scripts: list):
        self.scripts = list(scripts)  # each call pops a scripted hello/error
        self.calls = []
    def connect_hello(self, *, url, connect_params):
        self.calls.append(("connect", url, connect_params))
        item = self.scripts.pop(0)
        if item.get("ok") is False:
            raise GatewayRpcError(item["error"]["code"], item["error"]["message"], item["error"].get("details"))
        return item["payload"]
    def request(self, *, url, connect_params, method, params):
        self.calls.append(("req", method, params))
        item = self.scripts.pop(0)
        if item.get("ok") is False:
            raise GatewayRpcError(...)
        return item["payload"]

def test_fast_path_no_rpc_when_write_token_cached(tmp_path):
    # save identity with device_token + scopes including write
    # ensure_registered should not call transport
    ...

def test_a1_silent_pair_stores_token(tmp_path):
    transport = FakeTransport([{
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
    }, {
        # cleanup list
        "ok": True,
        "payload": {"pending": [], "paired": [
            {"deviceId": "stale", "displayName": "agentira-daemon", "publicKey": "other"},
            {"deviceId": "ui", "displayName": "Control UI", "clientId": "openclaw-control-ui"},
        ]},
    }, {
        "ok": True,
        "payload": {"deviceId": "stale"},
    }])
    ident = ensure_registered(
        gateway_url="http://127.0.0.1:18789",
        gateway_token="gw",
        identity_path=tmp_path / "openclaw-device.json",
        transport=transport,
    )
    assert ident.device_token == "dev-tok-1"
    assert "operator.write" in ident.scopes
    # cleanup only agentira-daemon stale, not control-ui
    remove_calls = [c for c in transport.calls if c[0] == "req" and c[1] == "device.pair.remove"]
    assert remove_calls and remove_calls[0][2]["deviceId"] == "stale"

def test_a2_pending_then_poll_complete(tmp_path):
    # first connect NOT_PAIRED with requestId
    # self-approve with pairing-scoped backend connect succeeds
    # reconnect returns deviceToken
    ...

def test_self_approve_denied_raises_actionable(tmp_path):
    # NOT_PAIRED then approve returns forbidden / missing scope
    # ensure_registered raises RegistrationPendingError with instructions
    ...

def test_gateway_unreachable_retries_then_errors(tmp_path, monkeypatch):
    ...
```

- [ ] **Step 2: Run — fail**

```bash
cd agentira-cli && python -m pytest tests/test_openclaw_device.py -v
```

- [ ] **Step 3: Implement `ensure_registered` + real websocket transport**

Pseudo-flow:

```python
def ensure_registered(...):
    scopes = default_requested_scopes()
    ident = load_identity(path) or generate_identity(...)
    save if new
    if not force and ident.device_token and write_scope in ident.scopes:
        # optional: lightweight verify — try connect; on auth failure re-pair
        return ident

    # Registration attempt (cli/cli for silent pair on loopback)
    try:
        hello = transport.connect_hello(
            url=ws_url_with_token(gateway_token),
            connect_params=build_registration_connect_params(ident, gateway_token, scopes),
        )
    except GatewayRpcError as e:
        if e.code != "NOT_PAIRED":
            raise
        request_id = (e.details or {}).get("requestId")
        # A1 explicit self-approve
        try:
            _self_approve(transport, gateway_url, gateway_token, request_id)
        except Exception:
            raise RegistrationPendingError(request_id=request_id, device_id=ident.device_id)
        hello = transport.connect_hello(...)  # retry registration connect

    token = hello.get("auth", {}).get("deviceToken")
    granted = hello.get("auth", {}).get("scopes") or []
    if not token or write_scope not in granted:
        raise RegistrationError("paired but missing operator.write — run agentira daemon pair")
    ident.device_token = token
    ident.scopes = granted
    ident.registered_at_ms = int(time.time() * 1000)
    save_identity(ident, path)
    _cleanup_stale_agentira_devices(transport, gateway_token, ident)
    return ident
```

Real transport: thin wrapper around `websocket.create_connection`, same pattern as `executor.run_openclaw_ws` (challenge → connect → optional request).

Bounded retry for connection errors: 3 attempts, 1s/2s backoff, final message: `OpenClaw gateway unreachable at {url} — is OpenClaw running?`

- [ ] **Step 4: Run unit tests — pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(cli): ensure_registered A1 silent pair + A2 pending fallback

Pair via connect handshake (no device.pair.request RPC), store device
token, self-approve when possible, clean up stale agentira-daemon entries.

Co-Authored-By: Grok <grok@x.ai>
EOF
)"
```

---

### Task 4: Wire device token into connect params + executor

**Files:**
- Modify: `agentira-cli/agentira_cli/runtimes/gateway_connect.py`
- Modify: `agentira-cli/agentira_cli/daemon/executor.py` (`run_openclaw_ws` ~543–700)
- Modify: `agentira-cli/agentira_cli/daemon/core.py` (where gateway_token is read for openclaw)
- Test: `agentira-cli/tests/test_gateway_connect_contract.py` (extend), `agentira-cli/tests/test_openclaw_ws_logging.py` if it asserts auth shape

**Interfaces:**
- Consumes: `DeviceIdentity.device_token`, `build_device_connect_field`
- Produces: connect frames that use `auth: { deviceToken }` for execution; registration still uses `auth: { token }`

- [ ] **Step 1: Failing tests**

```python
def test_build_connect_params_device_token_auth():
    params = build_connect_params(
        "dev-tok",
        user_agent="agentira-daemon",
        auth_kind="deviceToken",
        device={"id": "x", "publicKey": "y", "signature": "z", "signedAt": 1, "nonce": "n"},
    )
    assert params["auth"] == {"deviceToken": "dev-tok"}
    assert params["device"]["id"] == "x"
    assert params["scopes"] == ["operator.read", "operator.write"]  # or discovered

def test_build_connect_params_shared_token_default_unchanged():
    params = build_connect_params("gw")
    assert params["auth"] == {"token": "gw"}
    assert "device" not in params or params.get("device") is None
```

- [ ] **Step 2: Implement gateway_connect extensions**

```python
def build_connect_params(
    token: str,
    *,
    user_agent: str = "agentira",
    auth_kind: str = "token",  # "token" | "deviceToken"
    device: dict | None = None,
    scopes: list[str] | None = None,
    client_id: str | None = None,
    client_mode: str | None = None,
    display_name: str | None = None,
) -> dict:
    auth: dict = {}
    if token:
        if auth_kind == "deviceToken":
            auth = {"deviceToken": token}
        else:
            auth = {"token": token}
    client = {
        "id": client_id or GATEWAY_CLIENT_ID,
        "version": CLIENT_VERSION,
        "platform": _platform.system().lower() or "unknown",
        "mode": client_mode or GATEWAY_CLIENT_MODE,
    }
    if display_name:
        client["displayName"] = display_name
    params = {
        "minProtocol": MIN_PROTOCOL,
        "maxProtocol": MAX_PROTOCOL,
        "client": client,
        "role": "operator",
        "scopes": scopes or ["operator.read", "operator.write"],
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
```

- [ ] **Step 3: Change `run_openclaw_ws`**

Rename parameter conceptually to auth token but document it must be the **device token** when available:

```python
async def run_openclaw_ws(
    gateway_url: str,
    gateway_token: str,  # keep name for call-site compat OR rename to auth_token
    ...
    *,
    device_identity: DeviceIdentity | None = None,
    ...
):
```

Inside `_ws_main`:
1. If `device_identity` with token: build device field from challenge nonce; `auth_kind="deviceToken"`; URL query can use device token
2. Else: legacy shared token path (only registration should use this — execution path should require identity)

Preferred: **require** device token for execution; if missing, call `ensure_registered` once (or fail with "run agentira daemon pair").

- [ ] **Step 4: core.py — resolve identity before openclaw dispatch**

Where `gateway_token` is taken from frame/runtime_info:

```python
from agentira_cli.runtimes.openclaw_device import ensure_registered
from agentira_cli.runtimes.openclaw import OpenClawRuntime

info = OpenClawRuntime.introspect(...)
identity = ensure_registered(
    gateway_url=info["gateway_url"] or gateway_url,
    gateway_token=info["gateway_token"] or gateway_token,
)
# pass identity.device_token into run_openclaw_ws
```

Do **not** send the shared gateway token as the execution auth once identity is registered.

- [ ] **Step 5: Run tests**

```bash
cd agentira-cli && python -m pytest tests/test_gateway_connect_contract.py tests/test_openclaw_device.py tests/test_openclaw_ws_logging.py -v
```

- [ ] **Step 6: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(cli): authenticate OpenClaw execution with device token

Connect frames carry signed device identity + auth.deviceToken; shared
gateway token is registration-only.

Co-Authored-By: Grok <grok@x.ai>
EOF
)"
```

---

### Task 5: `agentira daemon pair` command

**Files:**
- Modify: `agentira-cli/agentira_cli/commands/daemon.py`
- Modify: `agentira-cli/tests/test_daemon_commands.py`

**Interfaces:**
- Consumes: `ensure_registered(..., force=True)`, `load_identity`

- [ ] **Step 1: Failing test**

```python
def test_pair_command_calls_ensure_registered(temp_state, monkeypatch):
    from agentira_cli.commands import daemon
    called = {}
    def fake_ensure(**kwargs):
        called.update(kwargs)
        from agentira_cli.runtimes.openclaw_device import generate_identity
        ident = generate_identity(gateway_url="http://127.0.0.1:18789")
        ident.device_token = "t"
        ident.scopes = ["operator.read", "operator.write"]
        return ident
    monkeypatch.setattr("agentira_cli.runtimes.openclaw_device.ensure_registered", fake_ensure)
    # invoke pair command (typer or direct function)
    daemon.pair()
    assert called.get("force") is True
```

- [ ] **Step 2: Implement**

```python
@app.command("pair")
def pair(
    force: bool = typer.Option(True, "--force/--no-force", help="Re-register even if a token exists"),
) -> None:
    """Register this daemon as an OpenClaw device with operator.write."""
    from agentira_cli.runtimes.openclaw import OpenClawRuntime
    from agentira_cli.runtimes.openclaw_device import ensure_registered, RegistrationPendingError, RegistrationError
    info = OpenClawRuntime.introspect("openclaw")
    url = info.get("gateway_url") or ""
    tok = info.get("gateway_token") or ""
    if not url or not tok:
        typer.echo("OpenClaw gateway URL/token not found. Is OpenClaw installed and configured?", err=True)
        raise typer.Exit(1)
    try:
        ident = ensure_registered(gateway_url=url, gateway_token=tok, force=force)
    except RegistrationPendingError as e:
        typer.echo("Pairing request is pending approval.")
        typer.echo(f"  request id: {e.request_id}")
        typer.echo(f"  Approve with: openclaw devices approve {e.request_id}")
        typer.echo("  Or approve in the OpenClaw Control UI, then re-run: agentira daemon pair")
        raise typer.Exit(2)
    except RegistrationError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    typer.echo(f"✓ OpenClaw device registered")
    typer.echo(f"  device_id: {ident.device_id}")
    typer.echo(f"  scopes:    {', '.join(ident.scopes)}")
```

Call `ensure_registered` from `_start_impl` / daemon boot as well (best-effort log on pending).

- [ ] **Step 3: Run tests — pass**

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(cli): agentira daemon pair — OpenClaw device registration

Force re-registration, print A2 approve instructions when pending.

Co-Authored-By: Grok <grok@x.ai>
EOF
)"
```

---

### Task 6: Docs

**Files:**
- Modify: `docs/forge_openclaw_setup.md`
- Modify: `docs/daemon_runbook.md`

- [ ] **Step 1: Update forge setup** — replace "copy the gateway token into Forge agent config for WS" narrative for the **daemon** path with: daemon auto-registers on start; shared token is read from `openclaw.json` only for pairing; customers run `agentira daemon pair` if prompted. Keep hooks/token notes for any remaining HTTP paths if still accurate.

- [ ] **Step 2: Add runbook failure mode**

```markdown
### N. Agent fails with `missing scope: operator.write`

**Symptom:** OpenClaw dispatch logs `missing scope: operator.write`.

**Cause:** Daemon is not registered as a write-scoped OpenClaw device (or is
using the shared gateway token without a signed device identity).

**Fix:**
1. `openclaw devices list --json` — find `displayName: agentira-daemon` (or
   your daemon's device); confirm scopes include `operator.write`.
2. `agentira daemon pair` — re-register.
3. If pending: `openclaw devices approve <requestId>` then re-run pair.
4. `agentira daemon restart`

Never edit scopes by hand in `openclaw.json`.
```

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs: OpenClaw daemon auto-registration + write-scope runbook

Co-Authored-By: Grok <grok@x.ai>
EOF
)"
```

---

### Task 7: End-to-end verification (local machine)

**Not a unit test — run on the dev machine with OpenClaw up.**

- [ ] **Step 1: Editable install + pair**

```bash
cd agentira-cli && pip install -e .
agentira daemon pair
openclaw devices list --json | python3 -c "import sys,json; d=json.load(sys.stdin); print([x for x in d['paired'] if 'agentira' in (x.get('displayName') or '')])"
```

Expected: device with `operator.write` in scopes.

- [ ] **Step 2: Restart daemon and send a chat/agent turn through Forge**

```bash
agentira daemon restart
# Trigger a chat that uses OpenClaw runtime from the UI, or a minimal WS agent call
```

Expected: no `missing scope: operator.write` in `agentira daemon logs`.

- [ ] **Step 3: Regression unit suite**

```bash
cd agentira-cli && python -m pytest tests/ -q --tb=line
```

- [ ] **Step 4: Final commit if any fixes; push branch**

```bash
git push -u origin feat/openclaw-daemon-registration
# open PR when green
```

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| Own device identity + device token auth | 2, 3, 4 |
| Persist `~/.agentira/openclaw-device.json` 0600 | 2 |
| `ensure_registered` fast path / A1 / A2 | 3 |
| `agentira daemon pair` | 5 |
| executor uses device token | 4 |
| Never write openclaw.json | global |
| Unit tests faked RPC | 3 |
| Contract test vs installed OpenClaw | 1 |
| Runtime scope discovery + fallback | 1 |
| Docs forge setup + runbook | 6 |
| E2E verify write error gone | 7 |
| `device.pair.request` in design | **Corrected:** connect-handshake pairing; plan documents proof |

**Placeholder scan:** none intentional — wire shapes quoted from live OpenClaw 2026.4.25.

**Type consistency:** `DeviceIdentity` fields used uniformly; `auth_kind` values `token` | `deviceToken`.
