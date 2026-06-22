"""AP-306: password lifecycle + email-required signup.

Covers admin reset (force-change), self change-password, forgot/reset-by-token,
email required on invite-accept, and admin email backfill. Mirrors the SQLite
TestClient harness used by the other *_rest tests.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from testcontainers.postgres import PostgresContainer

from backend.db import Base
from backend import services as core_services
from backend import passwords, email_sender
import backend.forge.models  # noqa: F401 — FK target registration
from backend.rest_api import app
from backend.jwt_auth import create_token


@pytest.fixture(scope="module")
def pg_engine():
    """Spawn a throwaway Postgres just for this module — no reliance on any
    shared/long-lived container. Torn down when the module finishes."""
    with PostgresContainer("postgres:16-alpine") as pg:
        engine = create_engine(pg.get_connection_url())
        yield engine
        engine.dispose()


@pytest.fixture
def env(pg_engine):
    """Yield (client, ctx) where ctx carries org + the seeded member's id.

    `client` is authed as the org admin. The schema is rebuilt per test for
    isolation. email_sender is mocked at the module level so both callers
    (password_service + services) see it; ctx['mail'] is the reset-mail mock."""
    import backend.db as bdb
    engine = pg_engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with patch.object(bdb, "engine", engine), patch.object(bdb, "app_engine", engine), \
         patch.object(email_sender, "send_password_reset_email") as reset_mail, \
         patch.object(email_sender, "send_welcome_email"):
        from backend.db import privileged
        from backend.models import Org, Profile, Role
        with privileged(), bdb.SessionLocal() as db:
            core_services._seed_defaults(db)
            org = Org(name="TestOrg")
            db.add(org); db.flush()
            admin_role = db.query(Role).filter(Role.name == "admin").first()
            member_role = db.query(Role).filter(Role.name == "member").first()
            admin = Profile(name="admin", org_id=org.id, roles=[admin_role],
                            email="admin@x.io", password_hash=passwords.hash_password("adminpw"),
                            api_key="k_admin")
            member = Profile(name="bob", org_id=org.id, roles=[member_role],
                             email="bob@x.io", password_hash=passwords.hash_password("oldpw"),
                             api_key="k_bob")
            db.add_all([admin, member]); db.commit()
            ctx = {"org_id": org.id, "member_id": member.id, "mail": reset_mail,
                   "admin_token": create_token("admin", admin.id, "admin", org_id=org.id),
                   "member_token": create_token("bob", member.id, "member", org_id=org.id)}
        c = TestClient(app)
        c.headers["Authorization"] = f"Bearer {ctx['admin_token']}"
        yield c, ctx


def _login(client, username, password):
    return client.post("/api/login", json={"username": username, "password": password})


# ── Admin reset ────────────────────────────────────────────────────────────

def test_admin_reset_generates_temp_and_forces_change(env):
    c, ctx = env
    r = c.post(f"/api/profiles/{ctx['member_id']}/reset-password", json={})
    assert r.status_code == 200
    temp = r.json()["temp_password"]
    assert temp  # a generated temp password was returned
    # old password no longer works; temp does
    assert _login(c, "bob", "oldpw").status_code == 401
    assert _login(c, "bob", temp).status_code == 200
    # account flagged to force a change
    me = c.get("/api/profiles/me", headers={"Authorization": f"Bearer {ctx['member_token']}"})
    assert me.json()["must_change_password"] is True


def test_admin_reset_with_explicit_password(env):
    c, ctx = env
    r = c.post(f"/api/profiles/{ctx['member_id']}/reset-password", json={"new_password": "set123"})
    assert r.status_code == 200 and r.json()["temp_password"] is None
    assert _login(c, "bob", "set123").status_code == 200


def test_admin_reset_requires_admin(env):
    c, ctx = env
    r = c.post(f"/api/profiles/{ctx['member_id']}/reset-password", json={},
               headers={"Authorization": f"Bearer {ctx['member_token']}"})
    assert r.status_code == 403


# ── Self change-password ─────────────────────────────────────────────────────

def test_change_own_password_no_current_needed(env):
    # JWT auth is sufficient — no re-entry of current password required.
    c, ctx = env
    r = c.post("/api/profiles/me/password", json={"new_password": "newpw123"},
               headers={"Authorization": f"Bearer {ctx['member_token']}"})
    assert r.status_code == 200
    assert _login(c, "bob", "newpw123").status_code == 200


def test_change_own_password_clears_must_change(env):
    c, ctx = env
    c.post(f"/api/profiles/{ctx['member_id']}/reset-password", json={"new_password": "temp1"})
    mtok = ctx["member_token"]
    r = c.post("/api/profiles/me/password", json={"new_password": "chosen1"},
               headers={"Authorization": f"Bearer {mtok}"})
    assert r.status_code == 200
    assert _login(c, "bob", "chosen1").status_code == 200
    me = c.get("/api/profiles/me", headers={"Authorization": f"Bearer {mtok}"})
    assert me.json()["must_change_password"] is False


# ── Forgot / reset by token ──────────────────────────────────────────────────

def test_forgot_password_sends_link_and_token_resets(env):
    c, ctx = env
    r = c.post("/api/auth/forgot-password", json={"email": "bob@x.io"})
    assert r.status_code == 200
    # a reset email was sent; pull the token out of the mocked call
    assert ctx["mail"].called
    token = ctx["mail"].call_args.args[2]
    r2 = c.post("/api/auth/reset-password", json={"token": token, "new_password": "viatoken1"})
    assert r2.status_code == 200
    assert _login(c, "bob", "viatoken1").status_code == 200


def test_forgot_password_unknown_email_is_silent_200(env):
    c, ctx = env
    r = c.post("/api/auth/forgot-password", json={"email": "nobody@x.io"})
    assert r.status_code == 200
    assert not ctx["mail"].send_password_reset_email.called


def test_reset_with_bad_token_rejected(env):
    c, _ = env
    r = c.post("/api/auth/reset-password", json={"token": "garbage", "new_password": "x"})
    assert r.status_code == 400


# ── Email required on signup; admin email backfill ──────────────────────────

def test_invite_accept_requires_email(env):
    c, ctx = env
    inv = core_services.create_invite(role="member", org_id=ctx["org_id"], invited_by="admin")
    # missing email → 422 (pydantic), present-but-blank → 400 (validation)
    assert c.post(f"/api/invites/{inv['code']}/accept",
                  json={"name": "carol", "password": "pw"}).status_code == 422
    assert c.post(f"/api/invites/{inv['code']}/accept",
                  json={"name": "carol", "password": "pw", "email": "nope"}).status_code == 400
    ok = c.post(f"/api/invites/{inv['code']}/accept",
                json={"name": "carol", "password": "pw", "email": "carol@x.io"})
    assert ok.status_code == 200 and ok.json()["user"]["email"] == "carol@x.io"


def test_invite_accept_duplicate_email_rejected(env):
    c, ctx = env
    inv = core_services.create_invite(role="member", org_id=ctx["org_id"], invited_by="admin")
    r = c.post(f"/api/invites/{inv['code']}/accept",
               json={"name": "dave", "password": "pw", "email": "bob@x.io"})
    assert r.status_code == 400


def test_admin_can_set_member_email(env):
    c, ctx = env
    r = c.patch(f"/api/profiles/{ctx['member_id']}", json={"email": "bob2@x.io"})
    assert r.status_code == 200 and r.json()["email"] == "bob2@x.io"
    # duplicate of admin's email → 400
    assert c.patch(f"/api/profiles/{ctx['member_id']}", json={"email": "admin@x.io"}).status_code == 400
