"""Admin view of invites sent for an org (pending / accepted / expired)."""
from backend.db import SessionLocal, privileged
from backend.models import Invite


def _utcnow():
    from backend.services import _utcnow
    return _utcnow()


def list_org_invites(org_id: str, limit: int = 50) -> list[dict]:
    now = _utcnow()
    with privileged(), SessionLocal() as db:
        rows = (db.query(Invite)
                .filter(Invite.org_id == org_id)
                .order_by(Invite.created_at.desc())
                .limit(limit).all())
        out = []
        for inv in rows:
            if inv.accepted_at:
                status = "accepted"
            elif inv.expires_at and inv.expires_at < now:
                status = "expired"
            else:
                status = "pending"
            item = {
                "id": inv.id, "email": inv.email, "status": status,
                "created_at": inv.created_at.isoformat(),
                "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
            }
            if status == "pending":
                item["code"] = inv.code
            out.append(item)
        return out


def cancel_org_invite(org_id: str, invite_id: str) -> str:
    """Delete an unaccepted invite of this org. Returns 'ok', 'not_found' or 'accepted'."""
    with privileged(), SessionLocal() as db:
        inv = (db.query(Invite)
               .filter(Invite.id == invite_id, Invite.org_id == org_id).first())
        if not inv:
            return "not_found"
        if inv.accepted_at:
            return "accepted"
        db.delete(inv)
        db.commit()
        return "ok"
