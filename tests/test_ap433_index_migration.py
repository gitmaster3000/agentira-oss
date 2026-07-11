"""AP-433: Task.project_id / Task.status_id gained index=True on the model
(#208), but Base.metadata.create_all() uses checkfirst=True — it only builds
schema (incl. indexes) for tables that don't already exist. On a real deploy
`tasks` already exists, so that model change alone never touches it. Same
gap for project_members.profile_id (needed once list_profiles moves off
per-row lazy-loads).

This proves the no-op (create_all alone, table pre-existing) and the fix
(run_migrations adds the indexes explicitly, idempotently).
"""
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

import backend.models  # noqa: F401
import backend.forge.models  # noqa: F401
from backend.db import Base, run_migrations


def _index_names(engine, table):
    return {ix["name"] for ix in inspect(engine).get_indexes(table)}


def test_create_all_alone_does_not_index_a_preexisting_table():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    # First create_all(): table doesn't exist yet, so it (incidentally)
    # would include index=True columns. Drop just the index to simulate the
    # real scenario — a table that existed *before* index=True was added to
    # the model — then run create_all() again, which is what init_db() does
    # on every boot.
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for name in _index_names(engine, "tasks"):
            if "project_id" in name or "status_id" in name:
                conn.exec_driver_sql(f"DROP INDEX {name}")
    Base.metadata.create_all(bind=engine)  # checkfirst=True: table exists, no-op
    names = _index_names(engine, "tasks")
    assert not any("project_id" in n for n in names)
    assert not any("status_id" in n for n in names)


def test_run_migrations_adds_the_indexes():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for name in _index_names(engine, "tasks"):
            if "project_id" in name or "status_id" in name:
                conn.exec_driver_sql(f"DROP INDEX {name}")

    TestSession = sessionmaker(bind=engine)
    with patch("backend.services.SessionLocal", TestSession):
        with patch("backend.db.engine", engine):
            run_migrations()

    assert "ix_tasks_project_id" in _index_names(engine, "tasks")
    assert "ix_tasks_status_id" in _index_names(engine, "tasks")
    assert "ix_tasks_epic_id" in _index_names(engine, "tasks")
    assert "ix_project_members_profile_id" in _index_names(engine, "project_members")


def test_run_migrations_is_idempotent():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)

    TestSession = sessionmaker(bind=engine)
    with patch("backend.services.SessionLocal", TestSession):
        with patch("backend.db.engine", engine):
            run_migrations()
            run_migrations()

    assert "ix_tasks_project_id" in _index_names(engine, "tasks")
    assert "ix_tasks_status_id" in _index_names(engine, "tasks")
    assert "ix_tasks_epic_id" in _index_names(engine, "tasks")
    assert "ix_project_members_profile_id" in _index_names(engine, "project_members")
