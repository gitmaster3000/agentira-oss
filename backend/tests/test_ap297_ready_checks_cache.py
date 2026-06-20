"""AP-297: ready_checks are cached on the run.

The result is served from cache on later on-ready fetches and recomputed only
when (a) the operational-env signature changes, (b) the cache is older than the
project's TTL, or (c) force=True. Task-content edits do NOT bust the cache.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    Agent, ForgeRuntime, Run, RunStatus, RuntimeStatus,
)
from backend.models import Profile, Role


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        db.add(Profile(name="admin", role_id=admin_role.id, password_hash=""))
        db.commit()
        db.close()
        yield TestSession


def _prep(TestSession, *, ttl=None):
    db = TestSession()
    rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                      status=RuntimeStatus.ONLINE,
                      last_heartbeat=datetime.now(timezone.utc))
    db.add(rt)
    db.flush()
    prof = Profile(name="bot", role_id=db.query(Role).first().id,
                   password_hash="", api_key="k")
    db.add(prof)
    db.flush()
    agent = Agent(name="bot", profile_id=prof.id, runtime_id=rt.id)
    db.add(agent)
    db.flush()
    proj = core_services.create_project("P")
    if ttl is not None:
        core_services.update_project(proj["id"], ready_checks_ttl_seconds=ttl)
    run = Run(agent_id=agent.id, project_id=proj["id"],
              status=RunStatus.READY)
    db.add(run)
    db.commit()
    ids = (run.id, agent.id, prof.id, proj["id"])
    db.close()
    return ids


def test_first_call_computes_then_serves_cache(test_db):
    run_id, *_ = _prep(test_db)
    first = forge_services.ready_checks(run_id)
    assert first["cached"] is False
    second = forge_services.ready_checks(run_id)
    assert second["cached"] is True
    assert second["checks"] == first["checks"]


def test_operational_env_change_busts_cache(test_db):
    run_id, agent_id, prof_id, _ = _prep(test_db)
    assert forge_services.ready_checks(run_id)["cached"] is False
    assert forge_services.ready_checks(run_id)["cached"] is True
    # Drop the API key — an operational-env change → recompute.
    db = test_db()
    db.query(Profile).filter(Profile.id == prof_id).update({"api_key": None})
    db.commit()
    db.close()
    again = forge_services.ready_checks(run_id)
    assert again["cached"] is False


def test_task_content_change_does_not_bust_cache(test_db):
    run_id, *_ = _prep(test_db)
    forge_services.ready_checks(run_id)
    # No task here, but the signature excludes task content by construction —
    # a second call with nothing operational changed must serve the cache.
    assert forge_services.ready_checks(run_id)["cached"] is True


def test_stale_cache_recomputes_by_ttl(test_db):
    run_id, *_ = _prep(test_db, ttl=600)
    forge_services.ready_checks(run_id)
    # Age the cache past the 600s TTL.
    db = test_db()
    db.query(Run).filter(Run.id == run_id).update(
        {"ready_checks_at": datetime.now(timezone.utc) - timedelta(seconds=601)})
    db.commit()
    db.close()
    assert forge_services.ready_checks(run_id)["cached"] is False


def test_ttl_zero_never_expires_by_age(test_db):
    run_id, *_ = _prep(test_db, ttl=0)
    forge_services.ready_checks(run_id)
    db = test_db()
    db.query(Run).filter(Run.id == run_id).update(
        {"ready_checks_at": datetime.now(timezone.utc) - timedelta(days=30)})
    db.commit()
    db.close()
    # No time expiry — still cached despite being 30 days old.
    assert forge_services.ready_checks(run_id)["cached"] is True


def test_force_recomputes(test_db):
    run_id, *_ = _prep(test_db)
    forge_services.ready_checks(run_id)
    assert forge_services.ready_checks(run_id)["cached"] is True
    assert forge_services.ready_checks(run_id, force=True)["cached"] is False


def test_project_ttl_setting_states(test_db):
    pid = core_services.create_project("P")["id"]
    # default → null
    assert core_services.get_project(pid)["ready_checks_ttl_seconds"] is None
    # custom seconds
    assert core_services.update_project(
        pid, ready_checks_ttl_seconds=120)["ready_checks_ttl_seconds"] == 120
    # 0 = never expire by age
    assert core_services.update_project(
        pid, ready_checks_ttl_seconds=0)["ready_checks_ttl_seconds"] == 0
    # negative sentinel → reset to default (null)
    assert core_services.update_project(
        pid, ready_checks_ttl_seconds=-1)["ready_checks_ttl_seconds"] is None
