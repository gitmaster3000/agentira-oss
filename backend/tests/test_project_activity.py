"""AP-74: the project activity summary endpoint — digest + Conductor view."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend import services as core_services
from backend.forge import services as forge_services  # noqa: F401
from backend.forge.router import get_project_activity


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg.SessionLocal


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
