"""Tests for Jira-style task keys."""
import re
import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend.services import (
    bootstrap, create_project, create_task, get_task,
    update_task, move_task, delete_task, add_comment,
    get_activity, link_commit, suggest_branch_name,
    get_board, _derive_prefix,
)

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    with patch("backend.services.SessionLocal", TestSession):
        with patch("backend.db.engine", engine):
            bootstrap()
            yield
    Base.metadata.drop_all(bind=engine)


# ── Prefix derivation ──────────────────────────────────────────────

def test_derive_prefix_multi_word():
    assert _derive_prefix("Agentira Platform") == "AP"
    assert _derive_prefix("My Cool Project") == "MCP"
    assert _derive_prefix("A B C D E F") == "ABCDE"

def test_derive_prefix_single_word():
    assert _derive_prefix("demo") == "DEMO"
    assert _derive_prefix("Agentira") == "GNTR"  # consonants

def test_derive_prefix_empty():
    assert _derive_prefix("") == "PROJ"
    assert _derive_prefix("123") == "PROJ"


# ── Project prefix ─────────────────────────────────────────────────

@patch("backend.services.SessionLocal", TestSession)
def test_project_gets_prefix():
    p = create_project("Test Project", actor="admin")
    assert "key_prefix" in p
    assert p["key_prefix"] == "TP"
    assert re.match(r'^[A-Z0-9]+$', p["key_prefix"])


@patch("backend.services.SessionLocal", TestSession)
def test_duplicate_prefix_dedup():
    p1 = create_project("Same Name", actor="admin")
    p2 = create_project("Same Name", actor="admin")
    assert p1["key_prefix"] != p2["key_prefix"]
    assert p2["key_prefix"].startswith("SN")


# ── Key generation ─────────────────────────────────────────────────

@patch("backend.services.SessionLocal", TestSession)
def test_task_gets_key():
    p = create_project("Alpha Beta", actor="admin")
    t1 = create_task(p["id"], "First task", actor="admin")
    t2 = create_task(p["id"], "Second task", actor="admin")
    assert t1["key"] == "AB-1"
    assert t2["key"] == "AB-2"
    # Key matches pattern
    assert re.match(r'^[A-Z]+-\d+$', t1["key"])


@patch("backend.services.SessionLocal", TestSession)
def test_key_in_task_dict():
    """Task dict includes key and all expected fields."""
    p = create_project("Field Check", actor="admin")
    t = create_task(p["id"], "Check fields", priority="high", actor="admin")
    assert "key" in t
    assert "id" in t
    assert "project_id" in t
    assert "title" in t
    assert "status" in t
    assert "priority" in t
    assert t["key"].startswith("FC-")
    assert t["priority"] == "high"


@patch("backend.services.SessionLocal", TestSession)
def test_keys_sequential_across_creates():
    """Keys increment sequentially even across multiple creates."""
    p = create_project("Seq Test", actor="admin")
    keys = []
    for i in range(5):
        t = create_task(p["id"], f"Task {i}", actor="admin")
        keys.append(t["key"])
    assert keys == ["ST-1", "ST-2", "ST-3", "ST-4", "ST-5"]


# ── Key-based lookups ──────────────────────────────────────────────

@patch("backend.services.SessionLocal", TestSession)
def test_get_task_by_key():
    p = create_project("Key Lookup", actor="admin")
    t = create_task(p["id"], "Find me", actor="admin")
    by_id = get_task(t["id"])
    by_key = get_task(t["key"])
    assert by_id["title"] == "Find me"
    assert by_key["title"] == "Find me"
    assert by_id["key"] == by_key["key"]


@patch("backend.services.SessionLocal", TestSession)
def test_get_task_by_key_case_insensitive():
    """Key lookup works case-insensitively."""
    p = create_project("Case Test", actor="admin")
    t = create_task(p["id"], "Case task", actor="admin")
    lower = get_task(t["key"].lower())
    assert lower is not None
    assert lower["title"] == "Case task"


@patch("backend.services.SessionLocal", TestSession)
def test_get_nonexistent_key():
    assert get_task("FAKE-999") is None


# ── CRUD by key ────────────────────────────────────────────────────

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
def test_comment_by_key():
    p = create_project("Comment Keys", actor="admin")
    t = create_task(p["id"], "Commentable", actor="admin")
    result = add_comment(t["key"], "test comment", actor="admin")
    assert result["detail"] == "test comment"


# ── Board + branch ─────────────────────────────────────────────────

@patch("backend.services.SessionLocal", TestSession)
def test_board_includes_keys():
    """Board response includes key on every task."""
    p = create_project("Board Keys", actor="admin")
    create_task(p["id"], "BT1", actor="admin")
    create_task(p["id"], "BT2", actor="admin")
    board = get_board(p["id"])
    all_tasks = [t for col in board["columns"].values() for t in col]
    assert len(all_tasks) == 2
    for t in all_tasks:
        assert "key" in t
        assert re.match(r'^[A-Z]+-\d+$', t["key"])


@patch("backend.services.SessionLocal", TestSession)
def test_suggest_branch_uses_key():
    p = create_project("Branch Test", actor="admin")
    t = create_task(p["id"], "My Feature", actor="admin")
    result = suggest_branch_name(t["id"])
    assert t["key"].lower() in result["branch"]


@patch("backend.services.SessionLocal", TestSession)
def test_link_commit_by_key():
    p = create_project("Commit Keys", actor="admin")
    t = create_task(p["id"], "Linkable", actor="admin")
    c = link_commit(t["key"], sha="abc1234567890123456789012345678901234567", message="fix stuff")
    assert c["task_id"] == t["id"]
    assert c["sha"] == "abc1234567890123456789012345678901234567"
