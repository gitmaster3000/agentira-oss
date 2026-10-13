"""Browser telemetry intake: POST /api/client-logs.

The frontend batches what a user actually experienced — crashes, slow
interactions (typing/clicks that took long to paint), main-thread freezes,
API timings as the browser saw them (server time + network), page-load
timings — and posts them here. Each event becomes ONE JSON log line on
stdout, prefixed `CLIENT `, so production issues can be found from logs
instead of re-testing:

    railway logs -s backend --filter "CLIENT" --since 1d

Auth is optional so a crash on the login/signup page is still reported; a
valid token adds the user/org to every line. Payloads are size-capped and
rate-limited per client IP. Only whitelisted fields are kept.

Levels: every browser runs "info" (crashes, slow interactions, failed/slow
calls). "debug" (lower thresholds, every call) is switched on per user for
a limited time — by an admin:

    POST   /api/client-logs/debug   {"user": "babar", "minutes": 60}
    GET    /api/client-logs/debug   (active windows in your org)
    DELETE /api/client-logs/debug/babar

or automatically when that user's info-level data shows a crash or an interaction
slower than AUTO_SLOW_MS (AGENTIRA_TELEMETRY_AUTO_MINUTES, 0 = off). The
browser learns its level from the response to its own log POST and from
GET /api/client-logs/config at startup, so no extra polling.
"""

import json
import logging
import os
import sys
import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.jwt_auth import get_current_user_payload, payload_roles
from backend.repos import client_debug

router = APIRouter(prefix="/api/client-logs", tags=["telemetry"])

_log = logging.getLogger("agentira.client")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(levelname)s: CLIENT %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.DEBUG)
    _log.propagate = False

MAX_BODY = 64 * 1024
MAX_EVENTS = 100
RATE_PER_MIN = 30  # batches per client IP per minute
_STR_MAX = 500

# Event kinds and the fields each may carry. Anything else is dropped.
_FIELDS = {
    "error": {"message", "stack", "source", "component", "error_id"},
    "interaction": {"event", "duration", "target", "input_delay", "processing"},
    "longtask": {"duration", "count"},
    "api": {"method", "endpoint", "status", "duration", "ok"},
    "api_summary": {"endpoints"},
    "page_load": {"ttfb", "dom_ready", "load", "lcp", "transfer_kb"},
}
_COMMON = {"kind", "route", "t"}
_CONTEXT = {"session", "release", "ua", "tz", "net", "screen", "cpu", "mem", "self_ms", "level"}
_WARN_KINDS = {"interaction", "longtask"}
AUTO_SLOW_MS = 1000
AUTO_MINUTES = int(os.getenv("AGENTIRA_TELEMETRY_AUTO_MINUTES", "30"))

_hits: dict[str, deque] = {}


def _rate_ok(ip: str) -> bool:
    now = time.monotonic()
    q = _hits.setdefault(ip, deque())
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_PER_MIN:
        return False
    q.append(now)
    if len(_hits) > 10_000:  # bound memory; drop idle IPs
        for k in [k for k, v in _hits.items() if not v]:
            _hits.pop(k, None)
    return True


def _clean(v):
    if isinstance(v, str):
        return v[:_STR_MAX]
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    if isinstance(v, dict):
        return {str(k)[:100]: _clean(x) for k, x in list(v.items())[:50]}
    if isinstance(v, list):
        return [_clean(x) for x in v[:50]]
    return str(v)[:_STR_MAX]


def _user(request: Request) -> dict:
    """{user, org} from a valid bearer token; {} when anonymous or the token
    is bad — telemetry never 401s."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return {}
    try:
        from backend.jwt_auth import decode_token
        p = decode_token(auth[7:])
        if not p.get("sub") or not p.get("org_id"):
            return {}
        return {"user": p["sub"], "org": p["org_id"]}
    except Exception:
        return {}


def _level(who: dict) -> dict:
    if not who:
        return {"level": "info"}
    from backend.db import set_current_org
    set_current_org(who["org"])
    try:
        row = client_debug.active(who["org"], who["user"])
    except Exception:  # telemetry must never break the app
        _log.exception("client debug lookup failed")
        return {"level": "info"}
    if row is None:
        return {"level": "info"}
    return {"level": row.level, "until": row.until.isoformat()}


def _trouble(events: list) -> str | None:
    """Why this batch should switch the user to debug, or None."""
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("kind") == "error":
            return "auto: crash"
        d = ev.get("duration")
        if ev.get("kind") == "interaction" and isinstance(d, (int, float)) and d >= AUTO_SLOW_MS:
            return f"auto: slow interaction {int(d)}ms"
    return None


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


@router.get("/config")
def client_config(request: Request):
    return _level(_user(request))


def _level_after(who: dict, events: list) -> dict:
    """Current level; switches to debug first if this batch shows trouble.
    Sync (DB) — called from the async handler via the threadpool."""
    level = _level(who)
    if who and AUTO_MINUTES > 0 and level["level"] == "info":
        reason = _trouble(events)
        if reason:
            try:
                client_debug.enable(who["org"], who["user"], AUTO_MINUTES, reason, "auto")
                _log.warning(json.dumps({"kind": "debug_on", "user": who["user"],
                                         "org": who["org"], "reason": reason,
                                         "minutes": AUTO_MINUTES}, separators=(",", ":")))
                level = _level(who)
            except Exception:
                _log.exception("auto debug enable failed")
    return level


@router.post("")
async def client_logs(request: Request):
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return Response(status_code=413)
    ip = _client_ip(request)
    if not _rate_ok(ip):
        return Response(status_code=429)
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return Response(status_code=400)
    if not isinstance(body, dict) or not isinstance(body.get("events"), list):
        return Response(status_code=400)

    ctx = {k: _clean(body.get(k)) for k in _CONTEXT if k in body}
    who = _user(request)
    ctx.update(who)
    ctx["ip"] = ip

    for ev in body["events"][:MAX_EVENTS]:
        if not isinstance(ev, dict):
            continue
        kind = ev.get("kind")
        allowed = _FIELDS.get(kind)
        if allowed is None:
            continue
        line = {k: _clean(ev[k]) for k in (_COMMON | allowed) if k in ev}
        line.update(ctx)
        msg = json.dumps(line, separators=(",", ":"))
        if kind == "error":
            _log.error(msg)
        elif kind in _WARN_KINDS:
            _log.warning(msg)
        elif body.get("level") == "debug" and kind == "api":
            _log.debug(msg)  # every call, only sent while debugging a user
        else:
            _log.info(msg)

    return await run_in_threadpool(_level_after, who, body["events"][:MAX_EVENTS])


# ── Admin: switch debug telemetry on/off for a user ───────────────────────

def _admin(payload: dict = Depends(get_current_user_payload)) -> dict:
    if "admin" not in payload_roles(payload):
        raise HTTPException(403, "Admin only")
    return payload


class DebugOn(BaseModel):
    user: str = Field(min_length=1, max_length=120)
    minutes: int = Field(60, ge=1, le=24 * 60)
    reason: str = Field("", max_length=200)


def _row(r) -> dict:
    return {"user": r.profile_name, "level": r.level, "until": r.until.isoformat(),
            "reason": r.reason, "by": r.created_by}


@router.post("/debug")
def debug_on(body: DebugOn, admin: dict = Depends(_admin)):
    row = client_debug.enable(admin["org_id"], body.user, body.minutes,
                              body.reason or "admin", admin["sub"])
    _log.warning(json.dumps({"kind": "debug_on", "user": body.user, "org": admin["org_id"],
                             "reason": row.reason, "minutes": body.minutes, "by": admin["sub"]},
                            separators=(",", ":")))
    return _row(row)


@router.get("/debug")
def debug_list(admin: dict = Depends(_admin)):
    return [_row(r) for r in client_debug.list_active(admin["org_id"])]


@router.delete("/debug/{user}")
def debug_off(user: str, admin: dict = Depends(_admin)):
    return {"removed": client_debug.disable(admin["org_id"], user)}
