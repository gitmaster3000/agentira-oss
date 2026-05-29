"""Durable, on-disk record of in-flight turns (ADR 009 / AP-135 B2–B3).

The daemon's in-memory ``_inflight`` map is lost on restart, which is how a
chat turn became an un-killable zombie: a new daemon had no record of the
claude process the old one spawned (``start_new_session=True`` keeps it
alive), so a cancel frame found nothing to kill.

This module mirrors each live turn to a small JSON file keyed by *scope*, so:

  - one live turn per scope is enforced (a new turn overwrites the file),
  - stop-by-scope can find the pid even across a daemon/backend restart,
  - on startup the daemon reaps orphans a prior instance left running.

Layout::

    ~/.agentira/inflight/<sanitized-scope>.json
    {scope_key, trace_id, run_id, pid, started_at, daemon_id}

Stdlib-only and best-effort: a failed registry write must never break a
dispatch, so every entry point swallows and logs its own errors.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import time
from pathlib import Path

logger = logging.getLogger("agentira.daemon.inflight")

_SANITIZE = re.compile(r"[^A-Za-z0-9._-]+")


def _dir() -> Path:
    d = Path(os.path.expanduser("~/.agentira/inflight"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(scope_key: str) -> Path:
    # Scopes look like "task:<id>" / "chat:project:<id>" / "chat:default".
    # Sanitize to a flat filename; empty scope gets a stable bucket so
    # scope-less dispatches are still tracked (and reaped).
    name = _SANITIZE.sub("_", scope_key) or "_noscope"
    return _dir() / f"{name}.json"


def record(*, scope_key: str, trace_id: str, run_id: str,
           pid: int, daemon_id: str) -> None:
    """Write/overwrite the live-turn record for ``scope_key``.

    Overwriting enforces one live turn per scope. Best-effort.
    """
    if not scope_key:
        return
    payload = {
        "scope_key": scope_key,
        "trace_id": trace_id,
        "run_id": run_id or "",
        "pid": int(pid),
        "started_at": time.time(),
        "daemon_id": daemon_id,
    }
    try:
        path = _path(scope_key)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("inflight record failed scope=%s: %s", scope_key, exc)


def clear(*, scope_key: str, trace_id: str = "") -> None:
    """Remove the record for ``scope_key`` — but only if it still points at
    ``trace_id`` (when given), so a turn finishing late never clobbers a
    newer turn that already took the scope. Best-effort."""
    if not scope_key:
        return
    try:
        path = _path(scope_key)
        if not path.exists():
            return
        if trace_id:
            try:
                cur = json.loads(path.read_text(encoding="utf-8"))
                if cur.get("trace_id") and cur["trace_id"] != trace_id:
                    return  # a newer turn owns the scope now
            except (OSError, ValueError):
                pass
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("inflight clear failed scope=%s: %s", scope_key, exc)


def list_live() -> list[dict]:
    """Return every persisted record (caller filters by scope/run as needed)."""
    out: list[dict] = []
    try:
        for f in _dir().glob("*.json"):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return out


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive, just not ours to signal directly
    return True


def _kill_group(pid: int) -> None:
    """SIGTERM then SIGKILL the process *group* (claude is spawned with
    start_new_session=True, so its children share the group)."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(pid), sig)
        except ProcessLookupError:
            return
        except OSError as exc:
            logger.debug("killpg(%s, %s) failed: %s", pid, sig, exc)
            return
        if sig is signal.SIGTERM:
            time.sleep(0.2)  # brief grace before escalating


def cancel_scope(scope_key: str) -> bool:
    """Stop-by-scope fallback (ADR 009 / B6). Kill the process recorded for
    ``scope_key`` if it's still alive, then clear the record. Returns True
    iff a live process was found and signaled. Used when the daemon has no
    in-memory entry (lost track, e.g. across a restart) but a process may
    still be running for the scope."""
    if not scope_key:
        return False
    try:
        entry = json.loads(_path(scope_key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    pid = int(entry.get("pid", 0) or 0)
    killed = False
    if _pid_alive(pid):
        _kill_group(pid)
        killed = True
        logger.info("stop-by-scope killed pid=%s scope=%s trace=%s",
                    pid, scope_key, entry.get("trace_id", "-"))
    clear(scope_key=scope_key, trace_id=entry.get("trace_id", ""))
    return killed


def reap_orphans(*, daemon_id: str) -> list[dict]:
    """Startup reaper. A fresh daemon owns no in-memory inflight, so any
    persisted record is from a prior instance/crash. If its process is
    still alive it's an orphan (unkillable by the old route) → kill its
    group. Dead records are stale → drop. Returns the reaped records for
    logging. The current daemon_id is recorded for audit; we kill orphans
    regardless of which daemon spawned them (re-adoption needs the asyncio
    proc handle, which a fresh process can't recover)."""
    reaped: list[dict] = []
    for entry in list_live():
        scope = entry.get("scope_key", "")
        pid = int(entry.get("pid", 0) or 0)
        alive = _pid_alive(pid)
        if alive:
            logger.warning(
                "reaping orphan turn scope=%s trace=%s pid=%s (prior daemon=%s)",
                scope, entry.get("trace_id", "-"), pid,
                (entry.get("daemon_id") or "-")[:8],
            )
            _kill_group(pid)
            entry["reaped"] = "killed"
        else:
            entry["reaped"] = "stale"
        clear(scope_key=scope, trace_id=entry.get("trace_id", ""))
        reaped.append(entry)
    if reaped:
        logger.info("inflight reaper: %d record(s) cleared (daemon=%s)",
                    len(reaped), daemon_id[:8])
    return reaped
