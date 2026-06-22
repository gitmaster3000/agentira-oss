"""Shared test harness — every test runs against its OWN ephemeral Postgres.

Prod is Postgres, so tests are Postgres: a single throwaway container is spun
for the session (no shared/long-lived/mutable DB), and each test gets a fresh
schema + seeded defaults + a default org with the org-context pinned.

Why this shape:
  - The real `SessionLocal` is a RoutingSession whose `get_bind` reads the
    module-level `backend.db.engine` / `app_engine` AT CALL TIME, and carries
    the org-stamping / org-filter event hooks. Pointing those two module
    globals at the container is therefore enough to route EVERY module's
    `SessionLocal` (they all share the one object) at our test DB — no
    per-module `SessionLocal` patching needed.
  - With an org context set, `before_flush` stamps `org_id` on new rows, so
    fixtures can insert profiles/projects without spelling out org_id.
"""
from __future__ import annotations

import types

import pytest
from sqlalchemy import create_engine

from testcontainers.postgres import PostgresContainer

import backend.db as bdb
from backend.db import Base, privileged
from backend import services as core_services
import backend.forge.models  # noqa: F401 — register FK targets on Base


@pytest.fixture(scope="session")
def _pg_engine():
    """One throwaway Postgres for the whole test session; torn down at the end."""
    with PostgresContainer("postgres:16-alpine") as pg:
        engine = create_engine(pg.get_connection_url())
        yield engine
        engine.dispose()


@pytest.fixture
def pg(_pg_engine):
    """Fresh schema + seeded defaults + a default org, with the org context
    pinned and the app's engines routed at the container.

    Yields a namespace with `.engine`, `.org_id`, and `.SessionLocal` (the real
    routing sessionmaker). Tests/fixtures build on top: seed an admin with
    `org_id=pg.org_id`, mint tokens, drive the REST app, etc."""
    engine = _pg_engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # Route the real SessionLocal at the container (both privileged + scoped
    # binds), for the duration of the test.
    orig_engine, orig_app = bdb.engine, bdb.app_engine
    bdb.engine, bdb.app_engine = engine, engine
    try:
        with privileged(), bdb.SessionLocal() as db:
            core_services._seed_defaults(db)
            from backend.models import Org
            org = Org(name="TestOrg")
            db.add(org)
            db.commit()
            org_id = org.id
        bdb.set_current_org(org_id)
        try:
            yield types.SimpleNamespace(engine=engine, org_id=org_id,
                                        SessionLocal=bdb.SessionLocal)
        finally:
            bdb.set_current_org(None)
    finally:
        bdb.engine, bdb.app_engine = orig_engine, orig_app


@pytest.fixture
def seed_admin(pg):
    """Create an org admin in pg.org_id; return (admin_id, bearer_token)."""
    from backend.models import Profile, Role
    from backend.jwt_auth import create_token
    with privileged(), bdb.SessionLocal() as db:
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        admin = Profile(name="admin", account_type="human", roles=[admin_role],
                        org_id=pg.org_id, password_hash="")
        db.add(admin)
        db.commit()
        admin_id = admin.id
    return admin_id, create_token("admin", admin_id, ["admin"], org_id=pg.org_id)
