"""Tests for Jira-style task keys."""
import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db import Base
from backend.services import (
    bootstrap, create_project, create_task, get_task,
    update_task, move_task, delete_task, _derive_prefix,
)

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    with patch("backend.services.SessionLocal", TestSession):
        with patch("backend.db.engine", engine):
            bootstrap()
            yield
    Base.metadata.drop_all(bind=engine)


def test_derive_prefix():
    assert _derive_prefix("Agentira Platform") == "AP"
    assert _derive_prefix("My Cool Project") == "MCP"
    assert _derive_prefix("demo") == "DEMO"
    assert _derive_prefix("") == "PROJ"


@patch("backend.services.SessionLocal", TestSession)
def test_project_gets_prefix():
    p = create_project("Test Project", actor="admin")
    assert "key_prefix" in p
    assert p["key_prefix"] == "TP"


@patch("backend.services.SessionLocal", TestSession)
def test_task_gets_key():
    p = create_project("Alpha Beta", actor="admin")
    t1 = create_task(p["id"], "First task", actor="admin")
    t2 = create_task(p["id"], "Second task", actor="admin")
    assert t1["key"] == "AB-1"
    assert t2["key"] == "AB-2"


@patch("backend.services.SessionLocal", TestSession)
def test_get_task_by_key():
    p = create_project("Key Lookup", actor="admin")
    t = create_task(p["id"], "Find me", actor="admin")
    # By ID
    assert get_task(t["id"])["title"] == "Find me"
    # By key
    assert get_task(t["key"])["title"] == "Find me"


@patch("backend.services.SessionLocal", TestSession)
def test_update_task_by_key():
    p = create_project("Update Keys", actor="admin")
    t = create_task(p["id"], "Original", actor="admin")
    updated = update_task(t["key"], title="Renamed", actor="admin")
    assert updated["title"] == "Renamed"
    assert updated["key"] == t["key"]


@patch("backend.services.SessionLocal", TestSession)
def test_move_task_by_key():
    p = create_project("Move Keys", actor="admin")
    t = create_task(p["id"], "Moveable", actor="admin")
    moved = move_task(t["key"], "todo", actor="admin")
    assert moved["status"] == "todo"
    assert moved["key"] == t["key"]


@patch("backend.services.SessionLocal", TestSession)
def test_delete_task_by_key():
    p = create_project("Delete Keys", actor="admin")
    t = create_task(p["id"], "Deleteable", actor="admin")
    assert delete_task(t["key"]) is True
    assert get_task(t["key"]) is None


@patch("backend.services.SessionLocal", TestSession)
def test_duplicate_prefix_dedup():
    p1 = create_project("Same Name", actor="admin")
    p2 = create_project("Same Name", actor="admin")
    assert p1["key_prefix"] != p2["key_prefix"]
