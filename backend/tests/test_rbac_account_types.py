"""RBAC remodel: account_type (stored) decoupled from roles (many-to-many).

Spec under test:
  - Three stored account types: human / agentira_agent / external_agent.
  - Roles are pure permission tiers: admin / member / viewer. The legacy
    'bot' role is gone — agents/service accounts get a real role + a type.
  - A profile may hold MULTIPLE roles; its permissions are the UNION of every
    role's permissions plus profile-level extras.
  - Admin can change/assign an account's roles.
  - JWT carries a `roles` list; legacy single-`role` tokens still authorize.
  - Daemon WS + API-key auth keep working (admin-in-roles).
  - Service-account identity is keyed on account_type, not the old bot role.

Spawns its own ephemeral Postgres — no shared/mutable container.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from testcontainers.postgres import PostgresContainer

from backend.db import Base
from backend import services as core_services
from backend import auth as core_auth
from backend import passwords, email_sender, jwt_auth
import backend.forge.models  # noqa: F401 — FK target registration
from backend.rest_api import app
from backend.jwt_auth import create_token


@pytest.fixture(scope="module")
def pg_engine():
    with PostgresContainer("postgres:16-alpine") as pg:
        engine = create_engine(pg.get_connection_url())
        yield engine
        engine.dispose()


@pytest.fixture
def env(pg_engine):
    """(client, ctx); client authed as org admin. Schema rebuilt per test.

    Profiles are built the NEW way: a stored `account_type` + a `roles` list
    (many-to-many), no single role_id."""
    import backend.db as bdb
    engine = pg_engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with patch.object(bdb, "engine", engine), patch.object(bdb, "app_engine", engine), \
         patch.object(email_sender, "send_password_reset_email"), \
         patch.object(email_sender, "send_welcome_email"):
        from backend.db import privileged
        from backend.models import Org, Profile, Role
        with privileged(), bdb.SessionLocal() as db:
            core_services._seed_defaults(db)
            org = Org(name="TestOrg")
            db.add(org); db.flush()
            roles = {r.name: r for r in db.query(Role).all()}
            admin = Profile(name="admin", org_id=org.id, account_type="human",
                            email="admin@x.io", password_hash=passwords.hash_password("adminpw"),
                            api_key="k_admin")
            admin.roles = [roles["admin"]]
            member = Profile(name="bob", org_id=org.id, account_type="human",
                             email="bob@x.io", password_hash=passwords.hash_password("oldpw"),
                             api_key="k_bob")
            member.roles = [roles["member"]]
            db.add_all([admin, member]); db.commit()
            ctx = {"org_id": org.id, "member_id": member.id, "admin_id": admin.id,
                   "admin_token": create_token("admin", admin.id, ["admin"], org_id=org.id),
                   "member_token": create_token("bob", member.id, ["member"], org_id=org.id)}
        c = TestClient(app)
        c.headers["Authorization"] = f"Bearer {ctx['admin_token']}"
        yield c, ctx


def _perms(actor):
    import backend.db as bdb
    from backend.db import privileged
    with privileged(), bdb.SessionLocal() as db:
        return core_auth.get_permissions(db, actor)


def _set_roles(db_roles, *names):
    return [db_roles[n] for n in names]


# ── Role set: bot is gone ────────────────────────────────────────────────────

def test_seed_has_no_bot_role(env):
    import backend.db as bdb
    from backend.db import privileged
    from backend.models import Role
    with privileged(), bdb.SessionLocal() as db:
        names = {r.name for r in db.query(Role).all()}
    assert names == {"admin", "member", "viewer"}
    assert "bot" not in names


# ── Stored account_type ──────────────────────────────────────────────────────

def test_human_profile_reports_account_type(env):
    c, ctx = env
    me = c.get("/api/profiles/me").json()
    assert me["account_type"] == "human"


def test_service_account_is_external_agent_with_member_role(env):
    c, ctx = env
    sa = c.post("/api/service-accounts", json={"name": "ci-bot"}).json()
    assert sa["account_type"] == "external_agent"
    assert sa["roles"] == ["member"]   # real permission tier, not 'bot'
    assert sa["api_key"]
    # fetchable + listed as a service account, keyed on account_type not role
    assert c.get(f"/api/service-accounts/{sa['id']}").json()["api_key"]
    listed = {p["id"] for p in c.get("/api/service-accounts").json()}
    assert sa["id"] in listed


def test_managed_agent_is_agentira_agent_and_not_a_service_account(env):
    c, ctx = env
    import backend.db as bdb
    from backend.db import privileged
    from backend.models import Profile, Role
    with privileged(), bdb.SessionLocal() as db:
        member = db.query(Role).filter(Role.name == "member").first()
        p = Profile(name="planner", org_id=ctx["org_id"], account_type="agentira_agent",
                    roles=[member])
        db.add(p); db.commit(); pid = p.id
    assert c.get(f"/api/profiles/{pid}").json()["account_type"] == "agentira_agent"
    listed = {p["id"] for p in c.get("/api/service-accounts").json()}
    assert pid not in listed   # managed agents are NOT service accounts


# ── Many-to-many roles + permission union ────────────────────────────────────

def test_profile_can_hold_multiple_roles(env):
    c, ctx = env
    me = c.get("/api/profiles/me").json()
    assert isinstance(me["roles"], list)


def test_permissions_are_union_of_all_roles(env):
    """A profile whose FIRST role is permissionless (viewer) must still gain
    permissions from a later role (member) — proves union, not first-wins."""
    import backend.db as bdb
    from backend.db import privileged
    from backend.models import Role, Profile
    with privileged(), bdb.SessionLocal() as db:
        roles = {r.name: r for r in db.query(Role).all()}
        p = db.get(Profile, ctx_member(env))
        p.roles = _set_roles(roles, "viewer", "member")
        db.commit()
    perms = _perms("bob")
    assert "task.create" in perms          # contributed by member
    # viewer-only profile has none of member's perms
    with privileged(), bdb.SessionLocal() as db:
        roles = {r.name: r for r in db.query(Role).all()}
        org_id = env[1]["org_id"]
        v = Profile(name="vonly", org_id=org_id, account_type="human")
        v.roles = [roles["viewer"]]
        db.add(v); db.commit()
    assert "task.create" not in _perms("vonly")


def ctx_member(env):
    return env[1]["member_id"]


# ── Admin can change/assign roles ────────────────────────────────────────────

def test_admin_can_set_multiple_roles(env):
    c, ctx = env
    r = c.patch(f"/api/profiles/{ctx['member_id']}", json={"roles": ["admin", "member"]})
    assert r.status_code == 200
    assert sorted(r.json()["roles"]) == ["admin", "member"]
    # after re-login bob's token carries admin and can hit an admin-only route
    tok = c.post("/api/login", json={"username": "bob", "password": "oldpw"}).json()["token"]
    ok = c.get("/api/service-accounts", headers={"Authorization": f"Bearer {tok}"})
    assert ok.status_code == 200


def test_set_roles_requires_admin(env):
    c, ctx = env
    r = c.patch(f"/api/profiles/{ctx['member_id']}", json={"roles": ["admin"]},
                headers={"Authorization": f"Bearer {ctx['member_token']}"})
    assert r.status_code == 403


# ── JWT: roles list + legacy single-role back-compat ─────────────────────────

def test_login_token_carries_roles_list(env):
    c, ctx = env
    tok = c.post("/api/login", json={"username": "admin", "password": "adminpw"}).json()["token"]
    payload = jwt_auth.decode_token(tok)
    assert "admin" in payload["roles"]


def test_legacy_single_role_token_still_authorizes_admin(env):
    """Tokens minted before this change carry only `role`, no `roles`."""
    c, ctx = env
    now = int(time.time())
    legacy = pyjwt.encode(
        {"sub": "admin", "profile_id": ctx["admin_id"], "role": "admin",
         "org_id": ctx["org_id"], "iat": now, "exp": now + 3600},
        jwt_auth.JWT_SECRET, algorithm=jwt_auth.JWT_ALGORITHM)
    r = c.get("/api/service-accounts", headers={"Authorization": f"Bearer {legacy}"})
    assert r.status_code == 200


def test_member_roles_token_denied_admin(env):
    c, ctx = env
    r = c.get("/api/service-accounts", headers={"Authorization": f"Bearer {ctx['member_token']}"})
    assert r.status_code == 403


# ── Daemon WS auth ───────────────────────────────────────────────────────────

def test_daemon_ws_auth_accepts_admin_in_roles(env):
    from backend.forge.ws_dispatch import _auth_ws_token
    c, ctx = env
    assert _auth_ws_token(ctx["admin_token"], require_admin=True) is not None
    assert _auth_ws_token(ctx["member_token"], require_admin=True) is None
    # legacy single-role admin token still accepted
    now = int(time.time())
    legacy = pyjwt.encode(
        {"sub": "admin", "profile_id": ctx["admin_id"], "role": "admin",
         "org_id": ctx["org_id"], "iat": now, "exp": now + 3600},
        jwt_auth.JWT_SECRET, algorithm=jwt_auth.JWT_ALGORITHM)
    assert _auth_ws_token(legacy, require_admin=True) is not None


# ── API-key fallback identity (daemon / MCP) ─────────────────────────────────

def test_api_key_resolves_to_identity_with_roles(env):
    c, ctx = env
    prof = core_services.validate_api_key("k_admin")
    assert "admin" in prof["roles"]
    assert prof["account_type"] == "human"
    # and an API key works as a bearer on an authed endpoint
    r = c.get("/api/profiles", headers={"Authorization": "Bearer k_admin"})
    assert r.status_code == 200


# ── Service-account API key regeneration ─────────────────────────────────────

def test_regenerate_api_key(env):
    c, ctx = env
    sa = c.post("/api/service-accounts", json={"name": "rotate-me"}).json()
    old = sa["api_key"]
    r = c.post(f"/api/service-accounts/{sa['id']}/regenerate-key")
    assert r.status_code == 200
    new = r.json()["api_key"]
    assert new and new != old
    assert core_services.validate_api_key(new)["id"] == sa["id"]
    with pytest.raises(ValueError):
        core_services.validate_api_key(old)


# ── Human invites carry account_type=human + the invited role ────────────────

def test_member_invite_creates_human_member(env):
    c, ctx = env
    inv = core_services.create_invite(role="member", org_id=ctx["org_id"], invited_by="admin")
    r = c.post(f"/api/invites/{inv['code']}/accept",
               json={"name": "carol", "password": "pw", "email": "carol@x.io"})
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["account_type"] == "human"
    assert user["roles"] == ["member"]


# ── account_type derivation rule (used by the data backfill migration) ───────

def test_account_type_derivation_rule():
    derive = core_services._derive_account_type
    assert derive("bot", "rt_123") == "agentira_agent"
    assert derive("bot", None) == "external_agent"
    assert derive("bot", "") == "external_agent"
    assert derive("admin", None) == "human"
    assert derive("member", None) == "human"


def test_migration_converts_legacy_role_id_schema(pg_engine):
    """A pre-RBAC DB (single role_id, 'bot' role) → account_type + profile_roles,
    role_id dropped, bot role removed. This is the one-shot prod data path."""
    import backend.db as bdb
    from sqlalchemy import text
    from backend.models import Org, Profile
    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)
    with patch.object(bdb, "engine", pg_engine), patch.object(bdb, "app_engine", pg_engine):
        from backend.db import privileged
        with privileged(), bdb.SessionLocal() as db:
            core_services._seed_defaults(db)  # admin/member/viewer
            org = Org(name="Legacy"); db.add(org); db.flush()
            org_id = org.id
            member_id = db.execute(text("SELECT id FROM roles WHERE name='member'")).scalar()
            # Recreate the legacy shape: a 'bot' role + a role_id FK column, with
            # NO profile_roles rows (the single role lived only on role_id).
            db.execute(text("INSERT INTO roles (id, name) VALUES ('rbot', 'bot')"))
            db.execute(text("ALTER TABLE profiles ADD COLUMN role_id VARCHAR(12)"))
            # Build rows via the ORM so NOT-NULL columns get their defaults; the
            # account_type here is a stale placeholder the migration must fix.
            db.add_all([Profile(id="pa", org_id=org_id, name="agent1", account_type="human"),
                        Profile(id="ph", org_id=org_id, name="human1", account_type="human")])
            db.flush()
            # A bot WITHOUT a runtime → external_agent; a member → human. (The
            # bot+runtime→agentira_agent branch is covered by the unit test.)
            db.execute(text("UPDATE profiles SET role_id='rbot' WHERE id='pa'"))
            db.execute(text("UPDATE profiles SET role_id=:m WHERE id='ph'"), {"m": member_id})
            db.commit()
        with bdb.engine.connect() as conn:
            bdb._migrate_rbac_account_types(conn)
            conn.commit()
        with privileged(), bdb.SessionLocal() as db:
            from backend.models import Profile
            agent = db.get(Profile, "pa")
            human = db.get(Profile, "ph")
            assert agent.account_type == "external_agent"   # bot, no runtime
            assert human.account_type == "human"
            assert agent.role_names == ["member"]           # bot remapped to member
            assert human.role_names == ["member"]
            cols = [c["name"] for c in __import__("sqlalchemy").inspect(bdb.engine).get_columns("profiles")]
            assert "role_id" not in cols                    # legacy column dropped
            assert db.execute(text("SELECT 1 FROM roles WHERE name='bot'")).first() is None
