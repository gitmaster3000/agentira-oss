"""Tests for run-context fields on Project (AP-49).

Ensures repo_path + conventions_md round-trip cleanly through the service
layer and serializer, and update_project respects the partial-update
contract (None = leave unchanged, "" = explicitly clear).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

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


def test_project_serializer_surfaces_context_fields():
    """New projects expose repo_path + conventions_md as empty strings, not absent."""
    p = services.create_project("Context Project", "desc", actor="system")
    assert "repo_path" in p
    assert "conventions_md" in p
    assert p["repo_path"] == ""
    assert p["conventions_md"] == ""


def test_update_repo_path_persists():
    p = services.create_project("Repo Project", actor="system")
    updated = services.update_project(p["id"], repo_path="/tmp/some/repo")
    assert updated["repo_path"] == "/tmp/some/repo"

    # Reload via get_project — confirm DB persistence, not just return value.
    fetched = services.get_project(p["id"])
    assert fetched["repo_path"] == "/tmp/some/repo"


def test_update_conventions_md_persists_multiline():
    p = services.create_project("Conv Project", actor="system")
    md = "# Conventions\n\n- Use ruff\n- Feature branches only\n"
    updated = services.update_project(p["id"], conventions_md=md)
    assert updated["conventions_md"] == md
    assert services.get_project(p["id"])["conventions_md"] == md


def test_partial_update_leaves_other_context_fields_alone():
    """Updating only one field must not clobber the other (None means 'unchanged')."""
    p = services.create_project("Partial", actor="system")
    services.update_project(p["id"], repo_path="/a", conventions_md="hello")

    # Update only repo_path; conventions_md should remain.
    services.update_project(p["id"], repo_path="/b")
    after = services.get_project(p["id"])
    assert after["repo_path"] == "/b"
    assert after["conventions_md"] == "hello"


def test_explicit_empty_string_clears_field():
    """Passing '' (not None) is the documented way to clear a context field."""
    p = services.create_project("Clear", actor="system")
    services.update_project(p["id"], repo_path="/x", conventions_md="rules")
    services.update_project(p["id"], conventions_md="")
    after = services.get_project(p["id"])
    assert after["repo_path"] == "/x"
    assert after["conventions_md"] == ""


def test_update_project_unchanged_for_nonexistent_fields():
    """Updating without context kwargs must not touch repo_path/conventions_md."""
    p = services.create_project("Untouched", actor="system")
    services.update_project(p["id"], repo_path="/keep", conventions_md="keep")

    # Rename only — context fields must survive.
    services.update_project(p["id"], name="Renamed")
    after = services.get_project(p["id"])
    assert after["name"] == "Renamed"
    assert after["repo_path"] == "/keep"
    assert after["conventions_md"] == "keep"
