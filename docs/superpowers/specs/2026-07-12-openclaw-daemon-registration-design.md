# Agentira daemon → OpenClaw device registration

**Status:** approved design · 2026-07-12
**Scope:** `agentira-cli` (daemon). No backend changes.

## Problem

Agent execution fails at the OpenClaw gateway with:

```
⚠ Agent execution failed: {'code': 'INVALID_REQUEST', 'message': 'missing scope: operator.write'}
```

The daemon authenticates to OpenClaw by reading the **shared** `gateway.auth.token`
from `~/.openclaw/openclaw.json` (`agentira_cli/runtimes/openclaw.py:74`) and
connecting as a generic client. OpenClaw grants such a client its default scope
set (`CLI_DEFAULT_OPERATOR_SCOPES`), which includes `operator.read` but **not**
`operator.write`. Effective scopes are `min(token authority, client-mode default
policy)`, so no amount of token power grants write — the client identity is
wrong. Confirmed on a live gateway: the daemon's device entry
(`clientId:"cli"`, `clientMode:"cli"`) has
`operator.read, operator.admin, operator.approvals, operator.pairing` and no
`operator.write`, while every properly-paired operator device has the full set.

Riding the shared token is the root fragility: the daemon inherits whatever
scopes that token/mode happens to yield, per customer, per OpenClaw version.

## Goal

The daemon obtains `operator.write` reliably on every customer install, with
the least setup friction, using OpenClaw's real pairing protocol — no edits to
`openclaw.json`, no manual scope surgery.

## Approach (approved)

Register the daemon as its **own OpenClaw device** with explicitly requested
scopes, then authenticate with the issued device token instead of the shared
gateway token.

OpenClaw exposes the primitives (verified in the installed dist,
`openclaw 2026.4.25`): `device.pair.request` / `node.pair.approve` /
`node.pair.list` / `node.pair.reject`, and pairing requests carry a
`requestedScopes` field.

**A1 (silent auto-register) with A2 (one-tap approve) fallback**, plus docs.

## Identity model

A dedicated device identity persisted on the Agentira side:

`~/.agentira/openclaw-device.json`
```json
{
  "device_id": "<from gateway on approval>",
  "public_key": "<base64>",
  "private_key": "<base64, 0600>",
  "device_token": "<issued on approval>",
  "scopes": ["operator.read", "operator.write"],
  "gateway_url": "http://127.0.0.1:18789",
  "registered_at_ms": 0
}
```

- Keypair generated once, on first registration.
- File mode `0600` (holds a private key + device token).
- The connect frame (`gateway_connect.py`) authenticates with `device_token`,
  not the shared `gateway.auth.token`. `requestedScopes` /
  `scopes: ["operator.read","operator.write"]` is already in the frame.

## Registration flow

`ensure_registered(gateway_url, gateway_token) -> DeviceIdentity`, idempotent,
invoked on daemon start before the first dispatch and by `agentira daemon pair`.

1. **Fast path.** Load `openclaw-device.json`; if it has a device token whose
   granted scopes include `operator.write` (verify against the gateway, e.g.
   `node.pair.list`/a whoami probe), return it. No-op on every normal start.
2. **Request.** Generate keypair if absent. Send `device.pair.request` with
   `requestedScopes: ["operator.read","operator.write"]`, a stable label
   (`agentira-daemon`), `clientMode: backend`.
3. **A1 — self-approve.** Using the local `gateway.auth.token` (the loopback
   trust root) approve the pending request via the pair-approve RPC. Store the
   returned `device_id` + `device_token`. Silent, zero customer interaction.
4. **A2 — fallback.** If self-approve is denied (token lacks
   `operator.approvals`/`operator.pairing`), leave the request pending and
   emit an actionable message: run `agentira daemon pair` or approve in the
   OpenClaw Control UI / `openclaw devices approve <id>`. The daemon polls
   `node.pair.list` and completes once approved.
5. **Cleanup.** After a new write-scoped device is active, revoke the stale
   generic `cli` pairing (`devices revoke`/`remove`) so no dead entry lingers.
   Only remove entries this daemon created (match by label/public key) — never
   touch operator devices.

`agentira daemon pair` — new command: force re-registration, print pending /
approved status, and surface the A2 instructions.

## Connect path change

`daemon/executor.py` currently passes the shared `gateway_token` into
`build_connect_params` and the WS URL (`?auth.token=`). Change: resolve the
device identity via `ensure_registered` once at daemon start, cache it, and
pass `device_token` on every dispatch. The shared gateway token is used **only**
during registration/approval, never for execution.

## Error handling

- **Still missing write after registration** → error names the exact remedy
  (`openclaw devices list` shows the Agentira device's scopes; re-run
  `agentira daemon pair`), not a raw gateway code.
- **Pairing RPC unreachable / gateway starting up** → bounded retry with a
  clear "gateway unreachable, is OpenClaw running?" message (same spirit as the
  release-fetch resilience already added).
- **Never write to `openclaw.json`.** Registration touches only pairing RPCs and
  Agentira-side state (`~/.agentira/`).
- File I/O on `openclaw-device.json` failures degrade to a clear error, not a
  silent fallback to the unscoped shared token.

## Docs

- `docs/forge_openclaw_setup.md`: replace the "copy the gateway token" step with
  the auto-registration flow; document the A2 one-tap approve fallback and
  `agentira daemon pair`.
- `docs/daemon_runbook.md`: add a "daemon ↔ OpenClaw registration" failure mode
  (symptom = `missing scope: operator.write`; check the Agentira device's
  scopes; re-pair).

## Testing

- **Unit** (faked OpenClaw RPC client):
  - fast path returns cached write-scoped identity, no RPC calls;
  - request → self-approve → token stored (A1);
  - self-approve denied → pending + manual-approve completes (A2);
  - stale `cli` device cleaned up, operator devices untouched;
  - gateway-unreachable → bounded retry then actionable error.
- **Contract** (against installed OpenClaw, like `test_gateway_connect_contract.py`):
  - `requestedScopes` includes `operator.write`;
  - the connect frame authenticates with the device token, not the shared token.

## Out of scope

- Backend / gateway-side changes.
- Non-OpenClaw runtimes (Ollama has no auth; unaffected).
- Multi-operator / remote (Tailscale) gateway approval UX beyond the A2 message.

## To confirm during implementation (not design-blocking)

Exact param shapes for `device.pair.request` and the approve RPC (field names,
whether approval is same-connection or a separate authenticated call), read from
the installed OpenClaw dist + `docs.openclaw.ai`. The flow above holds
regardless; only wire-level details are TBD.
