"""AP-296: per-repo worktree freshness policy on ProjectRepo."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.models import Profile, Role


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        db.add(Profile(name="admin", role_id=admin_role.id, password_hash=""))
        db.commit()
        db.close()
        yield TestSession


def _project() -> str:
    return core_services.create_project("P")["id"]


def test_default_is_always_latest():
    pid = _project()
    row = core_services.add_project_repo(pid, name="backend", repo_url="u",
                                         is_primary=True)
    assert row["worktree_freshness"] == "always_latest"


def test_update_accepts_known_policy():
    pid = _project()
    core_services.add_project_repo(pid, name="backend", repo_url="u")
    row = core_services.update_project_repo(pid, "backend",
                                            worktree_freshness="pinned")
    assert row["worktree_freshness"] == "pinned"


def test_update_rejects_unknown_policy():
    pid = _project()
    core_services.add_project_repo(pid, name="backend", repo_url="u")
    row = core_services.update_project_repo(pid, "backend",
                                            worktree_freshness="whenever")
    assert "error" in row
