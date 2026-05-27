"""Backend mirror of the daemons' live in-flight turns (ADR 009 / AP-135 B4).

Each daemon reports its live turns on every heartbeat (~5s). We keep the
latest snapshot per daemon so the backend can answer "what turn is live for
this scope?" — and "is anything live here?" for the always-on Stop button —
without depending on the in-process ``_TRACE_SCOPE`` map, which is lost on a
backend restart. A daemon restart re-populates this within one heartbeat.

Deliberately in-memory: it is a cache of daemon-owned truth, refreshed
continuously. The durable record of a turn lives in the daemon's on-disk
inflight registry; this is just the backend's rolling view of it.

Entries age out (``max_age_s``) so a daemon that stopped heartbeating (crash,
machine off) doesn't leave a phantom "live" turn the UI would offer Stop on.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
# scope_key -> {trace_id, run_id, pid, started_at, daemon_id, reported_at}
_by_scope: dict[str, dict] = {}


def set_for_daemon(daemon_id: str, entries: list[dict] | None) -> None:
    """Replace this daemon's contribution with its reported snapshot.

    Entries it no longer reports are dropped (the turn finished), so the
    view self-heals every heartbeat."""
    now = time.time()
    with _lock:
        for k in [k for k, v in _by_scope.items()
                  if v.get("daemon_id") == daemon_id]:
            _by_scope.pop(k, None)
        for e in entries or []:
            scope = (e or {}).get("scope_key")
            if not scope:
                continue
            _by_scope[scope] = {
                "trace_id": e.get("trace_id", ""),
                "run_id": e.get("run_id", ""),
                "pid": e.get("pid"),
                "started_at": e.get("started_at"),
                "daemon_id": daemon_id,
                "reported_at": now,
            }


def lookup_trace(scope_key: str, *, max_age_s: float = 30.0) -> str:
    """The live turn's trace_id for ``scope_key``, or "" if none/stale."""
    if not scope_key:
        return ""
    with _lock:
        e = _by_scope.get(scope_key)
        if not e or (time.time() - e.get("reported_at", 0)) > max_age_s:
            return ""
        return e.get("trace_id", "") or ""


def is_live(scope_key: str, *, max_age_s: float = 30.0) -> bool:
    """True iff a daemon recently reported a live turn for this scope."""
    return bool(lookup_trace(scope_key, max_age_s=max_age_s))
