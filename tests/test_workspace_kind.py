"""AP-197: project workspace_kind / repo_url plumbing in backend.services
and the run_migrations backfill.

In-memory SQLite + StaticPool + SessionLocal injection, mirroring
tests/test_api.py and tests/test_dispatch_bundle.py.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

# Import all model modules so create_all() builds the FULL schema (incl.
# ProjectRepo and FK targets) — partial imports leave dangling FKs.
import backend.models  # noqa: F401
import backend.forge.models  # noqa: F401
from backend.db import Base
from backend import services


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession):
        db = TestSession()
        services._seed_defaults(db)
        db.close()
        yield TestSession


# ── update_project: repo_url + workspace_kind ────────────────────────────

def test_update_project_sets_repo_url_and_workspace_kind():
    p = services.create_project("P")
    out = services.update_project(
        p["id"], repo_url="https://github.com/o/r.git", workspace_kind="git"
    )
    assert out["repo_url"] == "https://github.com/o/r.git"
    assert out["workspace_kind"] == "git"


def test_update_project_invalid_workspace_kind_ignored():
    p = services.create_project("P")
    services.update_project(p["id"], workspace_kind="git")
    out = services.update_project(p["id"], workspace_kind="bogus")
    # Junk is ignored; the previously-set value persists.
    assert out["workspace_kind"] == "git"


def test_update_project_empty_workspace_kind_clears():
    p = services.create_project("P")
    services.update_project(p["id"], workspace_kind="git")
    out = services.update_project(p["id"], workspace_kind="")
    assert out["workspace_kind"] == ""  # NULL surfaces as "" in the dict


def test_update_project_empty_repo_url_clears():
    p = services.create_project("P")
    services.update_project(p["id"], repo_url="https://github.com/o/r.git")
    out = services.update_project(p["id"], repo_url="")
    assert out["repo_url"] == ""


def test_update_project_accepts_each_valid_kind():
    for kind in ("git", "sandbox", "local_folder"):
        p = services.create_project(f"P-{kind}")
        out = services.update_project(p["id"], workspace_kind=kind)
        assert out["workspace_kind"] == kind


# ── update_project_repo ──────────────────────────────────────────────────

def test_update_project_repo_sets_repo_url():
    p = services.create_project("P")
    services.add_project_repo(
        p["id"], name="main", repo_path="/abs/path", is_primary=True
    )
    out = services.update_project_repo(
        p["id"], "main", repo_url="https://github.com/o/r.git"
    )
    assert "error" not in out
    assert out["repo_url"] == "https://github.com/o/r.git"


def test_update_project_repo_unknown_repo_returns_error():
    p = services.create_project("P")
    out = services.update_project_repo(p["id"], "nope", repo_url="x")
    assert "error" in out


def test_update_project_repo_rejects_relative_path():
    p = services.create_project("P")
    services.add_project_repo(p["id"], name="main", repo_path="/abs", is_primary=True)
    out = services.update_project_repo(
        p["id"], "main", repo_path="Users/me/proj"
    )
    assert "error" in out
    assert "absolute" in out["error"].lower()


# ── _project_to_dict exposes the new fields ──────────────────────────────

def test_project_dict_exposes_repo_url_and_workspace_kind():
    p = services.create_project("P")
    got = services.get_project(p["id"])
    assert "repo_url" in got
    assert "workspace_kind" in got


# ── run_migrations() backfill of workspace_kind ──────────────────────────

def test_run_migrations_backfills_workspace_kind(tmp_path):
    """Build a legacy `projects` table WITHOUT workspace_kind, seed three
    rows (git / local_folder / sandbox shapes), then run the real migration
    against that engine and assert the backfill."""
    from backend import db as db_mod

    eng = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE projects ("
            " id VARCHAR PRIMARY KEY,"
            " name VARCHAR,"
            " repo_path VARCHAR,"
            " repo_url VARCHAR"
            ")"
        ))
        conn.execute(text(
            "INSERT INTO projects (id, name, repo_path, repo_url) VALUES"
            " ('g', 'git-proj',   NULL,        'https://github.com/o/r.git'),"
            " ('l', 'local-proj', '/abs/path', NULL),"
            " ('s', 'sandbox',    NULL,        NULL)"
        ))

    # run_migrations() operates on the module-level engine; swap it in.
    with patch.object(db_mod, "engine", eng):
        db_mod.run_migrations()

    with eng.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(projects)"))}
        assert "workspace_kind" in cols
        rows = {r[0]: r[1] for r in
                conn.execute(text("SELECT id, workspace_kind FROM projects"))}
    assert rows["g"] == "git"
    assert rows["l"] == "local_folder"
    assert rows["s"] == "sandbox"
