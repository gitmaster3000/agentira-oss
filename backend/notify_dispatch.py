"""Creation notifications (task / bug / epic) fanned out to project members.

Each member chooses, per event and per channel (in-app, email, phone push),
what they receive. In-app rows are written inside the caller's transaction;
email and push go out only after that transaction commits.
"""
from __future__ import annotations

import json
import logging
import os
import threading

from sqlalchemy import event
from sqlalchemy.orm import Session

from backend import email_sender
from backend.models import Notification
from backend.notifications import broker
from backend.repos import notification_prefs as repo

log = logging.getLogger("agentira.notify")

EVENTS = ("task.created", "bug.created", "epic.created")
CHANNELS = ("in_app", "email", "push")
DEFAULTS = {"in_app": True, "email": False, "push": False}
_LABEL = {"task.created": "task", "bug.created": "bug", "epic.created": "epic"}


def _merge(stored: str | None) -> dict:
    saved = json.loads(stored) if stored else {}
    return {e: {c: bool(saved.get(e, {}).get(c, DEFAULTS[c])) for c in CHANNELS} for e in EVENTS}


def load_prefs(db, profile_id: str) -> dict:
    return _merge(repo.get_prefs_json(db, [profile_id]).get(profile_id))


def save_prefs(db, profile_id: str, patch: dict, org_id: str | None = None) -> dict:
    """Merge `patch` ({event: {channel: bool}}) into the stored prefs."""
    for ev, chans in patch.items():
        if ev not in EVENTS or not set(chans) <= set(CHANNELS):
            raise ValueError(f"unknown event/channel in {ev}: {chans}")
    merged = load_prefs(db, profile_id)
    for ev, chans in patch.items():
        merged[ev].update({c: bool(v) for c, v in chans.items()})
    if org_id is None:
        from backend.models import Profile
        org_id = db.get(Profile, profile_id).org_id
    repo.set_prefs_json(db, profile_id, org_id, json.dumps(merged))
    return merged


def notify_created(db, *, event_name: str, project_id: str, project_name: str,
                   actor: str, title: str, link: str, skip_in_app: tuple[str, ...] = ()) -> None:
    """Stage in-app rows now; queue email/push to run after `db` commits."""
    members = [m for m in repo.project_human_members(db, project_id) if m.name != actor]
    if not members:
        return
    ids = [m.id for m in members]
    stored = repo.get_prefs_json(db, ids)
    subs = repo.subscriptions_for(db, ids)
    label = _LABEL[event_name]
    heading = f"New {label}: {title}"
    meta = json.dumps({"project": project_name, "actor": actor})
    jobs = db.info.setdefault("notify_jobs", [])
    for m in members:
        p = _merge(stored.get(m.id))[event_name]
        if p["in_app"] and m.name not in skip_in_app:
            db.add(Notification(org_id=m.org_id, profile_id=m.id, type=event_name,
                                title=heading[:255], link=link[:255], meta=meta))
            jobs.append(("wake", m.id, None))
        if p["email"] and m.email:
            jobs.append(("email", m.email, (f"[{project_name}] {heading}",
                                            f"{actor} created a {label} in {project_name}:\n\n{title}\n\n"
                                            f"{email_sender.app_base_url()}/studio{link}\n")))
        if p["push"]:
            payload = json.dumps({"title": f"{project_name}: new {label}", "body": title,
                                  "url": f"/studio{link}"})
            for s in subs.get(m.id, []):
                jobs.append(("push", s, payload))


def notify_admins(db, *, event_name: str, title: str, body: str, link: str) -> int:
    """One in-app notification per workspace admin, plus a phone push to the
    admins who registered one. Rows are staged now; push goes out after `db`
    commits. Returns how many admins were notified."""
    admins = repo.admin_profiles(db)
    if not admins:
        return 0
    subs = repo.subscriptions_for(db, [a.id for a in admins])
    jobs = db.info.setdefault("notify_jobs", [])
    payload = json.dumps({"title": title, "body": body, "url": f"/studio{link}"})
    for a in admins:
        db.add(Notification(org_id=a.org_id, profile_id=a.id, type=event_name,
                            title=title[:255], link=link[:255],
                            meta=json.dumps({"summary": body})))
        jobs.append(("wake", a.id, None))
        for s in subs.get(a.id, []):
            jobs.append(("push", s, payload))
    return len(admins)


def _spawn(fn) -> None:
    threading.Thread(target=fn, daemon=True).start()


def _webpush(sub: dict, payload: str) -> bool:
    """Send one Web Push. False (and a log line) when unconfigured or rejected."""
    key = os.getenv("VAPID_PRIVATE_KEY", "")
    if not key:
        log.warning("VAPID_PRIVATE_KEY unset — skipping web push")
        return False
    from pywebpush import webpush, WebPushException
    try:
        webpush(sub, payload, vapid_private_key=key,
                vapid_claims={"sub": os.getenv("VAPID_SUBJECT", "mailto:admin@localhost")})
        return True
    except WebPushException as e:
        if getattr(e.response, "status_code", None) in (404, 410):  # subscription gone
            from backend.db import SessionLocal, privileged
            with privileged(), SessionLocal() as db:
                repo.delete_subscription(db, sub["endpoint"])
                db.commit()
        else:
            log.warning("web push failed: %s", e)
        return False


def _send(jobs: list) -> None:
    for kind, target, data in jobs:
        try:
            if kind == "email":
                email_sender.send_email(target, data[0], data[1])
            elif kind == "push":
                _webpush(target, data)
        except Exception:
            log.exception("notification %s delivery failed", kind)


@event.listens_for(Session, "after_commit")
def _after_commit(session) -> None:
    jobs = session.info.pop("notify_jobs", None)
    if not jobs:
        return
    for kind, target, _ in jobs:
        if kind == "wake":
            broker.notify(target)
    outbound = [j for j in jobs if j[0] != "wake"]
    if outbound:
        _spawn(lambda: _send(outbound))


@event.listens_for(Session, "after_rollback")
def _after_rollback(session) -> None:
    session.info.pop("notify_jobs", None)
