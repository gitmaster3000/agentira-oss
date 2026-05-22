"""AP-121: multi-repo per project.

A project can attach multiple git repos via project_repos. Tasks pick a
target with `tasks.repo_name`; NULL means the project's primary repo.
Legacy single-repo projects (no project_repos rows yet) keep working
via a synthetic fallback in resolve_project_repo.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
import backend.forge.models  # noqa: F401 — registers FK target tables
from backend.models import Project, ProjectRepo


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.db.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _make_project(TestSession, *, repo_path: str = "",
                  repo_url: str = "") -> str:
    p = core_services.create_project("P", actor="system")
    if repo_path or repo_url:
        with patch("backend.services.SessionLocal", TestSession):
            db = TestSession()
            row = db.query(Project).filter(Project.id == p["id"]).first()
            row.repo_path = repo_path or None
            row.repo_url = repo_url or None
            db.commit()
            db.close()
    return p["id"]


# ── add / list / remove ──────────────────────────────────────────────

def test_add_repo_returns_dict_with_is_primary(test_db):
    pid = _make_project(test_db)
    r = core_services.add_project_repo(
        pid, name="backend", repo_path="/tmp/backend",
    )
    assert r["name"] == "backend"
    # First repo on a fresh project is implicitly primary so dispatch
    # has a default target.
    assert r["is_primary"] is True


def test_add_second_repo_is_not_primary_by_default(test_db):
    pid = _make_project(test_db)
    core_services.add_project_repo(pid, name="backend", repo_path="/a")
    r2 = core_services.add_project_repo(pid, name="frontend", repo_path="/b")
    assert r2["is_primary"] is False


def test_explicit_is_primary_demotes_prior(test_db):
    pid = _make_project(test_db)
    core_services.add_project_repo(pid, name="backend", repo_path="/a")
    core_services.add_project_repo(
        pid, name="frontend", repo_path="/b", is_primary=True,
    )
    repos = core_services.list_project_repos(pid)
    by_name = {r["name"]: r for r in repos}
    assert by_name["frontend"]["is_primary"] is True
    assert by_name["backend"]["is_primary"] is False


def test_add_repo_rejects_duplicate_name(test_db):
    pid = _make_project(test_db)
    core_services.add_project_repo(pid, name="backend", repo_path="/a")
    res = core_services.add_project_repo(
        pid, name="backend", repo_path="/b",
    )
    assert "already" in (res.get("error") or "").lower()


def test_add_repo_requires_path_or_url(test_db):
    pid = _make_project(test_db)
    res = core_services.add_project_repo(pid, name="x")
    assert "required" in (res.get("error") or "").lower()


def test_list_orders_primary_first_then_creation(test_db):
    pid = _make_project(test_db)
    core_services.add_project_repo(pid, name="a", repo_path="/a")
    core_services.add_project_repo(pid, name="b", repo_path="/b")
    core_services.add_project_repo(
        pid, name="c", repo_path="/c", is_primary=True,
    )
    names = [r["name"] for r in core_services.list_project_repos(pid)]
    assert names[0] == "c"  # primary first
    assert names[1:] == ["a", "b"]  # creation order


def test_remove_promotes_next_to_primary(test_db):
    pid = _make_project(test_db)
    core_services.add_project_repo(pid, name="a", repo_path="/a")
    core_services.add_project_repo(pid, name="b", repo_path="/b")
    assert core_services.remove_project_repo(pid, "a") is True
    by_name = {r["name"]: r for r in core_services.list_project_repos(pid)}
    assert "a" not in by_name
    assert by_name["b"]["is_primary"] is True


def test_remove_unknown_repo_returns_false(test_db):
    pid = _make_project(test_db)
    assert core_services.remove_project_repo(pid, "ghost") is False


# ── resolve_project_repo ─────────────────────────────────────────────

def test_resolve_returns_named_repo(test_db):
    pid = _make_project(test_db)
    core_services.add_project_repo(pid, name="a", repo_path="/a")
    core_services.add_project_repo(pid, name="b", repo_path="/b")
    r = core_services.resolve_project_repo(pid, "b")
    assert r["name"] == "b"
    assert r["repo_path"] == "/b"


def test_resolve_returns_primary_when_name_is_none(test_db):
    pid = _make_project(test_db)
    core_services.add_project_repo(
        pid, name="a", repo_path="/a", is_primary=True,
    )
    core_services.add_project_repo(pid, name="b", repo_path="/b")
    r = core_services.resolve_project_repo(pid, None)
    assert r["name"] == "a"


def test_resolve_unknown_name_returns_none(test_db):
    pid = _make_project(test_db)
    core_services.add_project_repo(pid, name="a", repo_path="/a")
    assert core_services.resolve_project_repo(pid, "ghost") is None


def test_resolve_falls_back_to_legacy_project_repo_fields(test_db):
    """A project that hasn't been migrated yet (no project_repos rows)
    but has Project.repo_path set should still resolve."""
    pid = _make_project(test_db, repo_path="/legacy", repo_url="git://x")
    r = core_services.resolve_project_repo(pid, None)
    assert r is not None
    assert r["name"] == "primary"
    assert r["repo_path"] == "/legacy"
    assert r["repo_url"] == "git://x"


def test_resolve_returns_none_for_empty_project(test_db):
    pid = _make_project(test_db)  # no repos, no legacy fields
    assert core_services.resolve_project_repo(pid, None) is None
