"""Regression: saving an agent with no project (default_project_id="")
must NOT 500.

The "— none — (generic agent)" option in the config UI submits
default_project_id="". default_project_id is a nullable FK on both Agent
and Profile, so the empty string violates the FK (no project has id "")
and the PATCH returns 500. update_agent must coerce "" -> NULL.

Reproduced from prod: PATCH /api/forge/agents/<id> ->
psycopg2.errors.ForeignKeyViolation on profiles_default_project_id_fkey
with default_project_id=''. SQLite (test DB) doesn't enforce FKs, so we
assert on the stored value instead: it must be None, never "".
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import Agent, ForgeRuntime, RuntimeStatus
from backend.models import Profile


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _seed_runtime(TestSession) -> str:
    db = TestSession()
    rt = ForgeRuntime(
        daemon_id="test-daemon", provider="grok",
        binary_path="/tmp/grok", status=RuntimeStatus.ONLINE,
    )
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    return rt_id


def test_clear_default_project_stores_null(test_db):
    rt_id = _seed_runtime(test_db)
    project = core_services.create_project("P1", actor="system")
    agent = forge_services.create_agent(
        name="grok fullstack coder", executor_type="cli", runtime_id=rt_id,
    )

    # Assign a project, then clear it back to "none" — the failing flow.
    forge_services.update_agent(agent["id"], default_project_id=project["id"])
    result = forge_services.update_agent(agent["id"], default_project_id="")

    assert result is not None
    assert result["default_project_id"] is None

    db = test_db()
    assert db.get(Agent, agent["id"]).default_project_id is None
    assert db.get(Profile, agent["id"]).default_project_id is None
    db.close()


def test_empty_project_on_fresh_agent_stays_null(test_db):
    """No project ever set + saving with "" — must be None, not ""."""
    rt_id = _seed_runtime(test_db)
    agent = forge_services.create_agent(
        name="generic agent", executor_type="cli", runtime_id=rt_id,
    )

    result = forge_services.update_agent(
        agent["id"], model="grok-build", default_project_id="",
    )

    assert result["default_project_id"] is None
    db = test_db()
    assert db.get(Profile, agent["id"]).default_project_id is None
    db.close()
