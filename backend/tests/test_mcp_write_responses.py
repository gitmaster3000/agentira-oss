"""MCP mutations return small receipts unless full output is requested."""

from __future__ import annotations

import asyncio
import inspect

from backend import mcp_server


ROW_WRITE_TOOLS = (
    "update_profile",
    "create_project",
    "update_project",
    "add_project_member",
    "create_epic",
    "update_epic",
    "create_task",
    "update_task",
    "move_task",
    "add_dependency",
    "create_milestone",
    "update_milestone",
    "add_comment",
    "create_attachment",
)


def test_all_row_write_tools_offer_verbose_output():
    for name in ROW_WRITE_TOOLS:
        parameter = inspect.signature(getattr(mcp_server, name)).parameters["verbose"]
        assert parameter.default is False


def test_create_task_returns_id_and_key_by_default(monkeypatch):
    full = {
        "id": "task-1",
        "key": "AP-1",
        "title": "Ship it",
        "description": "A large field agents do not need echoed back",
    }
    monkeypatch.setattr(mcp_server.services, "create_task", lambda *args, **kwargs: full)

    result = asyncio.run(mcp_server.create_task("project-1", "Ship it"))

    assert result == {"id": "task-1", "key": "AP-1"}


def test_create_task_verbose_returns_full_object(monkeypatch):
    full = {
        "id": "task-1",
        "key": "AP-1",
        "title": "Ship it",
        "description": "Full output",
    }
    monkeypatch.setattr(mcp_server.services, "create_task", lambda *args, **kwargs: full)

    result = asyncio.run(
        mcp_server.create_task("project-1", "Ship it", verbose=True),
    )

    assert result == full


def test_add_dependency_returns_only_its_available_identifier(monkeypatch):
    full = {
        "id": "dependency-1",
        "project_id": "project-1",
        "task_id": "task-2",
        "depends_on_id": "task-1",
    }
    monkeypatch.setattr(
        mcp_server.services,
        "add_dependency",
        lambda *args, **kwargs: full,
    )

    compact = asyncio.run(
        mcp_server.add_dependency("project-1", "task-2", "task-1"),
    )
    verbose = asyncio.run(
        mcp_server.add_dependency(
            "project-1",
            "task-2",
            "task-1",
            verbose=True,
        ),
    )

    assert compact == {"id": "dependency-1"}
    assert verbose == full
