# ADR: Daemon device refresh tokens

Status: accepted · 2026-10-24

## Context

`agentira daemon login` gave the daemon a 7-day admin JWT and nothing else. On
2026-10-23 09:01 UTC it expired: every heartbeat returned 401 and the daemon
WebSocket was rejected (`daemon ws: rejected unauthenticated/non-admin connect`).
The daemon only logged at debug level, so no agent could run and nobody was told.

## Decision

- **Refresh token at login.** Approving a daemon login also issues a device refresh
  token (`daemon_refresh_tokens`: profile, org, device name, daemon id, created /
  last used / expires, used, revoked). Only the SHA-256 is stored. Lifetime 90 days,
  sliding: every exchange issues a new token with a fresh 90 days.
- **Exchange** — `POST /api/auth/cli/refresh {refresh_token}` (unauthenticated; the
  token is the credential) returns a new 7-day access JWT built from the profile's
  *current* roles, plus a rotated refresh token. The profile must still be an active
  admin; otherwise the family is revoked.
- **Rotation + reuse detection.** A token is single-use. Presenting an already-used
  token revokes its whole family (every token from that login) — the replay is
  either an attacker or a stale copy, and we cannot tell which. The retire step is
  an atomic `UPDATE … WHERE used_at IS NULL`, so concurrent exchanges cannot both win.
- **Revocation** — `POST /api/auth/cli/revoke` (called by `agentira daemon logout`)
  revokes the family.
- **Daemon** (`agentira_cli/daemon/auth.py`): refresh when < 24 h of access token
  remain, and on a 401 from REST (retry once) or WS (4401 / HTTP 401 → refresh, then
  the normal reconnect backoff). One lock serialises refreshes — two threads
  presenting the same token would trip reuse detection. On failure: backoff
  30 s → 10 min, one ERROR line per 10 minutes. A fresh `daemon login` is picked
  up from `credentials.json` without restart.
- **Visibility.** Runtime liveness is already the daemon WebSocket (a signed-out
  daemon is offline). We add `offline_reason` to the runtime payload — plain
  language, mentions sign-in after 5 minutes of silence.

## Compatibility

Old daemons (no refresh token) and static dev keys behave as before. The new
`start` body fields and `refresh_token` poll field are optional.

## Consequences / trade-offs

- A refresh response lost in transit (server rotated, daemon never saved) makes the
  next attempt look like reuse → family revoked → one manual `daemon login`. Chosen
  over a grace window to keep the rule simple and strict.
- Device sessions are not yet listed in the UI; revocation is by `daemon logout`
  or DB. A "Devices" admin list is the natural follow-up.
- Device-code sessions still live in process memory (single replica), unchanged.
