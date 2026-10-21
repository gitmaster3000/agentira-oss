"""Data access for notification preferences + Web Push subscriptions."""
from __future__ import annotations

from backend.models import NotificationPref, Profile, ProjectMember, PushSubscription


def project_human_members(db, project_id: str) -> list[Profile]:
    return (
        db.query(Profile)
        .join(ProjectMember, Profile.id == ProjectMember.profile_id)
        .filter(ProjectMember.project_id == project_id, Profile.account_type == "human")
        .all()
    )


def get_prefs_json(db, profile_ids: list[str]) -> dict[str, str]:
    rows = db.query(NotificationPref).filter(NotificationPref.profile_id.in_(profile_ids)).all()
    return {r.profile_id: r.prefs for r in rows}


def set_prefs_json(db, profile_id: str, org_id: str, prefs: str) -> None:
    row = db.get(NotificationPref, profile_id)
    if row:
        row.prefs = prefs
    else:
        db.add(NotificationPref(profile_id=profile_id, org_id=org_id, prefs=prefs))


def subscriptions_for(db, profile_ids: list[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for s in db.query(PushSubscription).filter(PushSubscription.profile_id.in_(profile_ids)):
        out.setdefault(s.profile_id, []).append(
            {"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}})
    return out


def upsert_subscription(db, profile: Profile, endpoint: str, p256dh: str, auth: str) -> None:
    row = db.query(PushSubscription).filter_by(endpoint=endpoint).first()
    if row:
        row.profile_id, row.p256dh, row.auth = profile.id, p256dh, auth
    else:
        db.add(PushSubscription(org_id=profile.org_id, profile_id=profile.id,
                                endpoint=endpoint, p256dh=p256dh, auth=auth))


def delete_subscription(db, endpoint: str, profile_id: str | None = None) -> None:
    q = db.query(PushSubscription).filter_by(endpoint=endpoint)
    if profile_id:
        q = q.filter_by(profile_id=profile_id)
    q.delete()
