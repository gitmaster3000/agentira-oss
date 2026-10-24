"""Work snapshot — a short, token-free picture of recent work and blockers.

`build_work_snapshot` is the one source: the scheduled night snapshot, the
`get_work_snapshot` MCP tool and the Conductor itself all read the same
thing. No LLM is involved; every number comes from real rows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.db import SessionLocal, get_current_org, privileged, set_current_org
from backend.forge.models import RunOutcome, RunStatus
from backend.forge.repos import snapshot as repo

logger = logging.getLogger("agentira.forge.snapshot")

# A daemon that has not checked in for this long is treated as offline.
OFFLINE_AFTER = timedelta(minutes=5)
CHAT_SCOPE = "chat:default"
_ITEM_CAP = 8
# Last job result per org id — a workspace only ever sees its own.
_LAST_SNAPSHOT: dict[str, dict] = {}


def get_last_snapshot(org_id: str | None = None) -> dict | None:
    return _LAST_SNAPSHOT.get(org_id or get_current_org() or "")


def _one_line(text: str | None, n: int = 160) -> str:
    line = " ".join((text or "").split())
    return line if len(line) <= n else line[:n - 1] + "…"


def _task_ref(t) -> dict:
    return {"key": t.key or "", "title": t.title}


def _run_ref(r, t) -> dict:
    return {**_task_ref(t), "summary": _one_line(r.summary or r.error)}


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _clock(dt: datetime) -> str:
    return _utc(dt).strftime("%H:%M UTC")


def _is_failed(r) -> bool:
    return r.outcome == RunOutcome.FAILED or (
        r.outcome is None and r.status == RunStatus.FAILED)


def _project_section(db, project, since: datetime, max_attempts: int) -> dict:
    ids = [project.id]
    finished = repo.runs_finished_since(db, project_ids=ids, since=since)
    runs = {k: [] for k in ("succeeded", "failed", "blocked", "needs_input")}
    for r, t in finished:
        if r.outcome == RunOutcome.SUCCEEDED:
            runs["succeeded"].append(_run_ref(r, t))
        elif r.outcome == RunOutcome.BLOCKED:
            runs["blocked"].append(_run_ref(r, t))
        elif r.outcome == RunOutcome.NEEDS_INPUT:
            runs["needs_input"].append(_run_ref(r, t))
        elif _is_failed(r):
            runs["failed"].append(_run_ref(r, t))

    blockers = []
    for r, t in repo.unanswered_question_runs(db, project_ids=ids):
        kind = "needs_input" if r.outcome == RunOutcome.NEEDS_INPUT else "blocked"
        blockers.append({**_task_ref(t), "kind": kind, "text": _one_line(r.summary)})
    for r, t in repo.tasks_with_spent_retries(db, project_ids=ids,
                                              max_attempts=max_attempts):
        blockers.append({**_task_ref(t), "kind": "retries_spent",
                         "text": _one_line(r.summary or r.error)})

    return {
        "name": project.name,
        "done": [_task_ref(t) for t in repo.tasks_in_status_since(
            db, project_ids=ids, status="done", since=since)],
        "to_review": [_task_ref(t) for t in repo.tasks_in_status_since(
            db, project_ids=ids, status="review", since=since)],
        "runs": runs,
        "in_flight": [_task_ref(t) for _, t in repo.live_runs(db, project_ids=ids)],
        "blockers": blockers,
    }


def _happened(p: dict) -> bool:
    return bool(p["done"] or p["to_review"] or any(p["runs"].values()))


def build_work_snapshot(since_hours: float = 8, project_id: str | None = None,
                        *, allowed_project_ids: list[str] | None = None) -> dict:
    """Snapshot of the last `since_hours`. `allowed_project_ids` narrows the
    projects (None = everything); machine health is only shown to callers who
    see everything."""
    from backend.forge import conductor
    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=since_hours)
    max_attempts = conductor.get_conductor_config()["redispatch_max_attempts"]
    with SessionLocal() as db:
        projects = [_project_section(db, p, since, max_attempts)
                    for p in repo.projects(db, project_id=project_id,
                                           allowed_ids=allowed_project_ids)]
        offline, last_beat = [], None
        if allowed_project_ids is None:
            offline = [{"device": rt.device_name or rt.daemon_id,
                        "provider": rt.provider,
                        "last_heartbeat": _utc(rt.last_heartbeat).isoformat()
                        if rt.last_heartbeat else None}
                       for rt in repo.stale_runtimes(db, cutoff=until - OFFLINE_AFTER)]
            last_beat = repo.last_daemon_heartbeat(db)
    snap = {
        "window": {"since": since.isoformat(), "until": until.isoformat(),
                   "hours": since_hours},
        "projects": projects,
        "health": {"runtimes_offline": offline,
                   "daemon_last_heartbeat": _utc(last_beat).isoformat()
                   if last_beat else None},
    }
    snap["happened"] = any(_happened(p) for p in projects)
    snap["has_blockers"] = bool(offline or any(p["blockers"] for p in projects))
    snap["markdown"] = render_markdown(snap)
    return snap


# ── Rendering (plain language) ───────────────────────────────────────

def _link(t: dict) -> str:
    return f"[{t['key']}](/studio/tasks/{t['key']})" if t["key"] else t["title"]


def _items(tasks: list[dict]) -> list[str]:
    out = [f"  - {_link(t)} {t['title']}" for t in tasks[:_ITEM_CAP]]
    if len(tasks) > _ITEM_CAP:
        out.append(f"  - …and {len(tasks) - _ITEM_CAP} more")
    return out


_BLOCKER_TEXT = {
    "needs_input": "is waiting for your answer",
    "blocked": "is stuck and needs help",
    "retries_spent": "keeps failing and the automatic retries are used up",
}


def render_markdown(snap: dict) -> str:
    hours = snap["window"]["hours"]
    lines = [f"# Work snapshot — last {hours:g} hours", ""]
    health, projects = snap["health"], snap["projects"]
    needs = []
    if health["runtimes_offline"]:
        beat = health["daemon_last_heartbeat"]
        since = (_clock(datetime.fromisoformat(beat)) if beat else "ever")
        needs.append(f"- Agents are offline: the daemon has not checked in "
                     f"since {since}. No work will start until it is back.")
    for p in projects:
        for b in p["blockers"]:
            why = f": “{b['text']}”" if b["text"] else ""
            needs.append(f"- {p['name']} · {_link(b)} {b['title']} "
                         f"{_BLOCKER_TEXT[b['kind']]}{why}")
    if needs:
        lines += ["## Needs you", *needs, ""]
    quiet = True
    for p in projects:
        runs = p["runs"]
        if not (_happened(p) or p["in_flight"]):
            continue
        quiet = False
        lines.append(f"## {p['name']}")
        if p["done"]:
            lines += [f"- Finished ({len(p['done'])}):", *_items(p["done"])]
        if p["to_review"]:
            lines += [f"- Ready for your review ({len(p['to_review'])}):",
                      *_items(p["to_review"])]
        counts = [f"{len(runs[k])} {label}" for k, label in
                  (("succeeded", "succeeded"), ("failed", "failed"),
                   ("blocked", "stuck"), ("needs_input", "waiting on you"))
                  if runs[k]]
        if counts:
            lines.append("- Agent runs: " + ", ".join(counts))
            for k in ("failed", "blocked", "needs_input"):
                for r in runs[k][:_ITEM_CAP]:
                    lines.append(f"  - {_link(r)} {r['summary'] or r['title']}")
        if p["in_flight"]:
            lines += [f"- Working on now ({len(p['in_flight'])}):",
                      *_items(p["in_flight"])]
        lines.append("")
    if quiet and not needs:
        lines.append("Quiet — nothing finished and nothing needs you.")
    return "\n".join(lines).rstrip() + "\n"


# ── Scheduled job ────────────────────────────────────────────────────

def _headline(snap: dict) -> tuple[str, str]:
    blockers = len(snap["health"]["runtimes_offline"]) + sum(
        len(p["blockers"]) for p in snap["projects"])
    done = sum(len(p["done"]) for p in snap["projects"])
    review = sum(len(p["to_review"]) for p in snap["projects"])
    bits = []
    if blockers:
        bits.append(f"{blockers} thing{'s' if blockers != 1 else ''} need you")
    if done:
        bits.append(f"{done} finished")
    if review:
        bits.append(f"{review} ready for review")
    body = ", ".join(bits) or "Some agent runs finished"
    return f"Work snapshot: {body}", body


def _org_ids() -> list[str]:
    from backend.models import Org
    with privileged(), SessionLocal() as db:
        return [o.id for o in db.query(Org).all()]


def _snapshot_org(org_id: str, hours: float) -> dict:
    """One org's snapshot, with that org pinned so every query, the admin
    list and the Conductor chat stay inside it."""
    from backend import notify_dispatch
    from backend.forge import conductor
    from backend.forge.repos import messages as messages_repo
    snap = build_work_snapshot(since_hours=hours)
    at = snap["window"]["until"]
    if not (snap["happened"] or snap["has_blockers"]):
        return {"posted": False, "reason": "quiet", "at": at}
    title, body = _headline(snap)
    with SessionLocal() as db:
        prof = conductor.conductor_for_org(db, org_id)
        notified = notify_dispatch.notify_admins(
            db, event_name="conductor.snapshot", title=title, body=body,
            link="/forge/conductor")
        if prof:
            messages_repo.add_note(db, agent_id=prof.id, scope_key=CHAT_SCOPE,
                                   content=snap["markdown"])
        db.commit()
    logger.info("Work snapshot posted org=%s: %s", org_id, body)
    return {"posted": True, "at": at, "notified": notified,
            "summary": body, "markdown": snap["markdown"]}


def run_snapshot_job() -> dict:
    """Scheduled every `conductor_snapshot_interval_hours`. Runs once per org
    with that org pinned; an org posts only when something happened in the
    window or a blocker exists — otherwise silent. The post is a notification
    to that org's admins plus a plain message in its Conductor's chat; it
    never starts an LLM turn."""
    from backend.forge import conductor

    hours = conductor.get_conductor_config()["snapshot_interval_hours"]
    if hours <= 0:
        return {"skipped": "snapshot_off"}
    if not conductor._conductor_active():
        return {"skipped": "conductor_disabled"}
    previous = get_current_org()
    results: dict[str, dict] = {}
    try:
        for org_id in _org_ids():
            set_current_org(org_id)
            results[org_id] = _LAST_SNAPSHOT[org_id] = _snapshot_org(org_id, hours)
    finally:
        set_current_org(previous)
    return {"posted": any(r["posted"] for r in results.values()), "orgs": results}
