"""AP-74: the project activity summary endpoint — digest + Conductor view."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.router import get_project_activity


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.conductor.SessionLocal", TestSession), \
         patch("backend.forge.digest.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def test_activity_returns_digest_and_conductor_view(test_db):
    project = core_services.create_project("P", actor="system")
    out = get_project_activity(project["id"])
    assert "digest" in out and "conductor" in out
    assert "counts" in out["digest"]
    assert "agents" in out["conductor"]
    # No conductor-enabled agents in this project yet.
    assert out["conductor"]["agents"] == []


def test_activity_unknown_project_404s(test_db):
    with pytest.raises(HTTPException) as exc:
        get_project_activity("ghost_project")
    assert exc.value.status_code == 404
