"""Subscription usage limits: classify the error, pause the run, resume at reset.

A run that hits a Claude/Codex usage limit is not failed. It is PAUSED with
`pause_reason="usage_limit"` and a `resume_at`; its runtime is marked limited so
no new run is dispatched to it; `resume_due_runs` (scheduler sweep) relaunches
the same session once the limit has reset.

Policy lives in config (env), not constants — see docs-oss/docs/technical/configuration.md:
  FORGE_LIMIT_FIRST_BACKOFF_S   wait after the first hit with no reset time (default 1800)
  FORGE_LIMIT_BACKOFF_S         wait after each further hit (default 3600)
  FORGE_LIMIT_RESET_GRACE_S     added to a parsed reset time (default 60)
  FORGE_LIMIT_MAX_PAUSES        consecutive hits before the run fails for real (default 48)
A per-agent fallback model is optional: `config_json` {"fallback_model": "<id>"}.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.db import SessionLocal
from backend.forge.models import Agent, AgentStatus, RunStatus
from backend.forge.repos import usage_limits as repo

logger = logging.getLogger("agentira.forge.usage_limits")


@dataclass(frozen=True)
class LimitHit:
    message: str
    reset_at: datetime | None  # None → no reset time in the message


@dataclass(frozen=True)
class Policy:
    first_backoff_s: int
    backoff_s: int
    reset_grace_s: int
    max_pauses: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def policy() -> Policy:
    def _i(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, default))
        except ValueError:
            return default
    return Policy(
        first_backoff_s=_i("FORGE_LIMIT_FIRST_BACKOFF_S", 1800),
        backoff_s=_i("FORGE_LIMIT_BACKOFF_S", 3600),
        reset_grace_s=_i("FORGE_LIMIT_RESET_GRACE_S", 60),
        max_pauses=_i("FORGE_LIMIT_MAX_PAUSES", 48),
    )


# ── classify ──────────────────────────────────────────────────────────

# claude: "You've hit your session limit · resets 6:20am (Europe/Berlin)",
#         "Claude AI usage limit reached|1759300000"
# codex:  "You've hit your usage limit. ... try again at 6:20 AM" / "in 2 hours 5 minutes"
_LIMIT_RE = re.compile(
    r"hit your (?:[\w-]+ )?limit|usage limit (?:reached|has been reached)|"
    r"session limit|weekly limit reached", re.I)
_EPOCH_RE = re.compile(r"limit reached\|(\d{10})")
_CLOCK_RE = re.compile(
    r"(?:resets?|try again at)\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)\b"
    r"(?:\s*\(([\w/+-]+)\))?", re.I)
_REL_RE = re.compile(
    r"try again in\s+(?:(\d+)\s*d\w*\s*)?(?:(\d+)\s*h\w*\s*)?(?:(\d+)\s*m\w*)?", re.I)


def _next_clock(now: datetime, hour12: int, minute: int, ampm: str, tzname: str | None) -> datetime:
    try:
        tz = ZoneInfo(tzname) if tzname else timezone.utc
    except Exception:  # noqa: BLE001 — unknown zone name → treat as UTC
        tz = timezone.utc
    hour = hour12 % 12 + (12 if ampm.lower() == "pm" else 0)
    local_now = now.astimezone(tz)
    target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local_now:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)


def classify(error: str | None, now: datetime | None = None) -> LimitHit | None:
    """LimitHit if `error` is a subscription usage-limit message, else None."""
    if not error or not _LIMIT_RE.search(error):
        return None
    now = now or _now()
    msg = error.strip()
    m = _EPOCH_RE.search(msg)
    if m:
        return LimitHit(msg, datetime.fromtimestamp(int(m.group(1)), timezone.utc))
    m = _CLOCK_RE.search(msg)
    if m:
        return LimitHit(msg, _next_clock(now, int(m.group(1)), int(m.group(2) or 0),
                                         m.group(3), m.group(4)))
    m = _REL_RE.search(msg)
    if m and any(m.groups()):
        d, h, mi = (int(g or 0) for g in m.groups())
        return LimitHit(msg, now + timedelta(days=d, hours=h, minutes=mi))
    return LimitHit(msg, None)


def resume_time(hit: LimitHit, prior_hits: int, now: datetime, pol: Policy) -> datetime:
    """Parsed reset (+ grace) when given, else 30 min then hourly backoff."""
    if hit.reset_at and hit.reset_at > now:
        return hit.reset_at + timedelta(seconds=pol.reset_grace_s)
    return now + timedelta(seconds=pol.first_backoff_s if prior_hits == 0 else pol.backoff_s)


def rest_label(resume_at: datetime | None) -> str:
    """Plain-words status for agent / run surfaces."""
    if not resume_at:
        return ""
    at = resume_at if resume_at.tzinfo else resume_at.replace(tzinfo=timezone.utc)
    return f"Resting until {at.astimezone(timezone.utc):%H:%M} UTC — usage limit"


def fallback_model(agent: Agent) -> str:
    try:
        return str((json.loads(agent.config_json or "{}") or {}).get("fallback_model") or "")
    except (ValueError, AttributeError):
        return ""


# ── pause / gate / resume ─────────────────────────────────────────────

def _utc(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def pause_on_limit(run_id: str, error: str, *, session_id: str = "",
                   now: datetime | None = None) -> dict | None:
    """If `error` is a usage limit, park the run (RUNNING → PAUSED) and mark its
    runtime limited. Returns {"resume_at", "label"} or None (not a limit, or the
    pause budget is spent → the caller fails the run normally)."""
    now = now or _now()
    hit = classify(error, now)
    if hit is None:
        return None
    pol = policy()
    with SessionLocal() as db:
        run = repo.get_run(db, run_id)
        # The agent's own finish_run verdict outranks the process error (AP-108).
        if run is None or run.outcome is not None or (run.limit_hits or 0) >= pol.max_pauses:
            return None
        agent = db.get(Agent, run.agent_id)
        resume_at = resume_time(hit, run.limit_hits or 0, now, pol)
        # An agent with a fallback model keeps working: resume right away on it.
        if agent is not None and fallback_model(agent):
            resume_at = now
        run.status = RunStatus.PAUSED
        run.pause_reason = repo.PAUSE_REASON
        run.resume_at = resume_at
        run.limit_hits = (run.limit_hits or 0) + 1
        run.error = None
        run.interrupt_intent = None
        run.stop_requested_at = None
        if session_id:
            run.session_id = session_id
        if agent is not None and agent.status == AgentStatus.BUSY:
            agent.status = AgentStatus.ONLINE
        rt = repo.runtime_for_agent(db, run.agent_id)
        if rt is not None:
            prev = _utc(rt.limited_until)
            rt.limited_until = max(prev, resume_at) if prev and prev > now else resume_at
            rt.limit_reason = hit.message[:300]
        db.commit()
    from backend.forge.runs import broadcast_status
    broadcast_status(run_id, RunStatus.PAUSED)
    logger.info("run %s paused on usage limit until %s", run_id, resume_at.isoformat())
    return {"resume_at": resume_at, "label": rest_label(resume_at)}


def runtime_limit(runtime_id: str | None, now: datetime | None = None) -> dict | None:
    """{"until", "label", "reason"} while the runtime is limited, else None."""
    if not runtime_id:
        return None
    now = now or _now()
    with SessionLocal() as db:
        if runtime_id not in repo.limited_runtime_ids(db, now):
            return None
        rt = repo.get_runtime(db, runtime_id)
        until = _utc(rt.limited_until)
        return {"until": until, "label": rest_label(until), "reason": rt.limit_reason or ""}


def resume_due_runs(now: datetime | None = None) -> list[str]:
    """Scheduler sweep: relaunch limit-paused runs whose resume_at has passed.
    A run whose runtime is still limited waits (unless its agent has a fallback
    model). Returns the ids it relaunched."""
    from backend.forge import services
    now = now or _now()
    with SessionLocal() as db:
        limited = repo.limited_runtime_ids(db, now)
        due = []
        for run in repo.due_paused_runs(db, now):
            agent = db.get(Agent, run.agent_id)
            fb = fallback_model(agent) if agent else ""
            if agent and agent.runtime_id in limited and not fb:
                continue
            due.append((run.id, fb))
    resumed: list[str] = []
    for run_id, fb in due:
        try:
            res = services.resume_run(run_id, model_override=fb)
        except Exception:  # noqa: BLE001 — one bad run must not stall the sweep
            logger.exception("auto-resume failed run=%s", run_id)
            continue
        if res.get("error"):
            logger.warning("auto-resume run=%s: %s", run_id, res["error"])
        else:
            resumed.append(run_id)
    return resumed
