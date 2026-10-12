"""AP-601: list_tasks filters by tag, epic_id and milestone_id."""

from __future__ import annotations

import pytest

from backend import services


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg


@pytest.fixture
def board():
    services.create_service_account("alice")
    pid = services.create_project("P", actor="alice")["id"]
    epic = services.create_epic(pid, "E", actor="alice")
    ms = services.create_milestone(pid, "M", actor="alice")
    a = services.create_task(pid, "a", tags=["mcp", "agentic-layer"],
                             epic_id=epic["id"], actor="alice")
    b = services.create_task(pid, "b", tags=["mcp-extra"],
                             milestone_id=ms["id"], actor="alice")
    c = services.create_task(pid, "c", actor="alice")
    return {"pid": pid, "epic": epic["id"], "ms": ms["id"],
            "a": a["id"], "b": b["id"], "c": c["id"]}


def _ids(board, **kw):
    return {t["id"] for t in services.list_tasks(board["pid"], actor="alice", **kw)}


def test_filter_by_tag_matches_whole_tag_only(board):
    assert _ids(board, tag="mcp") == {board["a"]}
    assert _ids(board, tag="agentic-layer") == {board["a"]}


def test_filter_by_epic_id(board):
    assert _ids(board, epic_id=board["epic"]) == {board["a"]}


def test_filter_by_milestone_id(board):
    assert _ids(board, milestone_id=board["ms"]) == {board["b"]}


def test_filters_combine(board):
    assert _ids(board, tag="mcp", epic_id=board["epic"]) == {board["a"]}
    assert _ids(board, tag="mcp", milestone_id=board["ms"]) == set()


def test_tag_wildcards_are_literal(board):
    assert _ids(board, tag="%") == set()
