"""Shared test harness — every test runs against its OWN ephemeral Postgres.

Prod is Postgres, so tests are Postgres: a throwaway container is spun per
pytest-xdist worker (or one for serial runs), schema is created once per
worker, and each test resets via TRUNCATE (much faster than drop_all/create_all).
"""

from __future__ import annotations

import types

import pytest
from sqlalchemy import create_engine, inspect, text

from testcontainers.postgres import PostgresContainer

import backend.db as bdb
from backend.db import Base, privileged
from backend import services as core_services
import backend.forge.models  # noqa: F401 — register FK targets on Base


def _truncate_all(engine) -> None:
    tables = inspect(engine).get_table_names()
    if not tables:
        return
    quoted = ", ".join(f'"{t}"' for t in tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def _pg_engine(worker_id):
    """One Postgres container per xdist worker (or one for serial runs)."""
    with PostgresContainer("postgres:16-alpine") as pg:
        engine = create_engine(pg.get_connection_url())
        Base.metadata.create_all(engine)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def pg(_pg_engine):
    """Fresh data on a shared schema, with org context pinned."""
    engine = _pg_engine
    _truncate_all(engine)
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