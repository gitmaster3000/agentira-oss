"""Daemon device refresh tokens: issued at `agentira daemon login`, exchanged
for a fresh access JWT + a rotated refresh token, reuse revokes the chain.

Runs on the shared ephemeral-Postgres harness (`pg` / `seed_admin`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.db import privileged
from backend.jwt_auth import decode_token
from backend.models import DaemonRefreshToken, Profile
from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    admin_id, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    c.admin_id = admin_id
    yield c


def _login(client, **start_body) -> dict:
    """Run the device-code flow end to end; return the poll response."""
    start = client.post("/api/auth/cli/start", json=start_body).json()
    ok = client.post("/api/auth/cli/approve", json={"user_code": start["user_code"]})
    assert ok.status_code == 200, ok.text
    res = client.post("/api/auth/cli/poll", json={"device_code": start["device_code"]})
    assert res.status_code == 200, res.text
    return res.json()


def _refresh(client, refresh_token: str):
    # Unauthenticated on purpose: the access token is expired by then.
    return TestClient(app).post("/api/auth/cli/refresh",
                                json={"refresh_token": refresh_token})


def _rows(pg):
    with privileged(), pg.SessionLocal() as db:
        return db.query(DaemonRefreshToken).order_by(DaemonRefreshToken.created_at).all()


def test_login_issues_refresh_token_and_stores_only_a_hash(client, pg):
    res = _login(client, device_name="Ali's Mac", daemon_id="d-123")
    assert res["status"] == "approved"
    assert res["token"] and res["refresh_token"]
    [row] = _rows(pg)
    assert row.profile_id == client.admin_id
    assert row.device_name == "Ali's Mac" and row.daemon_id == "d-123"
    assert row.token_hash != res["refresh_token"]
    assert res["refresh_token"] not in (row.token_hash, row.device_name)
    assert row.revoked_at is None and row.used_at is None
    days = (row.expires_at - datetime.now(timezone.utc)).days
    assert 88 <= days <= 90


def test_login_without_device_info_still_works(client, pg):
    res = _login(client)
    assert res["token"] and res["refresh_token"]


def test_exchange_returns_fresh_access_token_and_rotated_refresh_token(client, pg):
    first = _login(client)
    res = _refresh(client, first["refresh_token"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["refresh_token"] and body["refresh_token"] != first["refresh_token"]
    claims = decode_token(body["token"])
    assert claims["sub"] == "admin" and claims["org_id"] == pg.org_id
    assert "admin" in claims["roles"]
    # the new access token really authenticates the daemon endpoints
    r = TestClient(app).post(
        "/api/forge/runtimes/heartbeat",
        headers={"Authorization": f"Bearer {body['token']}"},
        json={"daemon_id": "d-1", "providers": [], "inflight": []})
    assert r.status_code == 200, r.text


def test_exchange_slides_expiry_and_stamps_last_used(client, pg):
    first = _login(client)
    with privileged(), pg.SessionLocal() as db:
        row = db.query(DaemonRefreshToken).one()
        row.expires_at = datetime.now(timezone.utc) + timedelta(days=2)
        db.commit()
    assert _refresh(client, first["refresh_token"]).status_code == 200
    old, new = _rows(pg)
    assert old.used_at is not None and old.last_used_at is not None
    assert (new.expires_at - datetime.now(timezone.utc)).days >= 88
    assert new.family_id == old.family_id


def test_old_refresh_token_is_dead_after_use(client, pg):
    first = _login(client)
    assert _refresh(client, first["refresh_token"]).status_code == 200
    assert _refresh(client, first["refresh_token"]).status_code == 401


def test_reuse_of_an_old_token_revokes_the_whole_chain(client, pg):
    first = _login(client)
    second = _refresh(client, first["refresh_token"]).json()
    # attacker (or a stale copy) replays the first token…
    assert _refresh(client, first["refresh_token"]).status_code == 401
    # …so the legitimately rotated one is dead too.
    assert _refresh(client, second["refresh_token"]).status_code == 401
    assert all(r.revoked_at is not None for r in _rows(pg))


def test_reuse_does_not_touch_other_devices(client, pg):
    mine = _login(client, daemon_id="a")
    other = _login(client, daemon_id="b")
    assert _refresh(client, mine["refresh_token"]).status_code == 200
    assert _refresh(client, mine["refresh_token"]).status_code == 401
    assert _refresh(client, other["refresh_token"]).status_code == 200


def test_expired_refresh_token_is_rejected(client, pg):
    first = _login(client)
    with privileged(), pg.SessionLocal() as db:
        db.query(DaemonRefreshToken).update(
            {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
        db.commit()
    assert _refresh(client, first["refresh_token"]).status_code == 401


def test_revoked_refresh_token_is_rejected(client, pg):
    first = _login(client)
    r = TestClient(app).post("/api/auth/cli/revoke",
                             json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    assert _refresh(client, first["refresh_token"]).status_code == 401


def test_revoke_kills_the_rotated_chain_too(client, pg):
    first = _login(client)
    second = _refresh(client, first["refresh_token"]).json()
    TestClient(app).post("/api/auth/cli/revoke",
                         json={"refresh_token": second["refresh_token"]})
    assert _refresh(client, second["refresh_token"]).status_code == 401


def test_unknown_or_missing_token_is_rejected(client, pg):
    assert _refresh(client, "nope").status_code == 401
    assert TestClient(app).post("/api/auth/cli/refresh", json={}).status_code == 401


def test_profile_no_longer_admin_cannot_refresh(client, pg):
    from backend.models import Role
    first = _login(client)
    with privileged(), pg.SessionLocal() as db:
        member = db.query(Role).filter(Role.name == "member").first()
        db.get(Profile, client.admin_id).roles = [member]
        db.commit()
    assert _refresh(client, first["refresh_token"]).status_code == 401
    assert all(r.revoked_at is not None for r in _rows(pg))


def test_archived_profile_cannot_refresh(client, pg):
    first = _login(client)
    with privileged(), pg.SessionLocal() as db:
        db.get(Profile, client.admin_id).archived_at = datetime.now(timezone.utc)
        db.commit()
    assert _refresh(client, first["refresh_token"]).status_code == 401
