"""AP-506: compact, scope-aware attachment CRD MCP surface."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from backend import mcp_server, services


@pytest.fixture(autouse=True)
def test_db_and_storage(pg, tmp_path):
    storage = tmp_path / "attachments"
    with patch.dict("os.environ", {"AGENTIRA_API_BASE_URL": ""}), patch(
        "backend.attachments.ATTACHMENTS_DIR", str(storage),
    ):
        yield


@contextmanager
def _actor(name: str):
    token = mcp_server.actor_ctx.set(name)
    try:
        yield
    finally:
        mcp_server.actor_ctx.reset(token)


def _scenario() -> tuple[dict, dict, dict]:
    services.create_service_account("alice")
    services.create_service_account("mallory")
    project = services.create_project("Private", actor="alice")
    task = services.create_task(project["id"], "Task", actor="alice")
    epic = services.create_epic(project["id"], "Epic", actor="alice")
    return project, task, epic


def test_attachment_tool_surface_is_three_crd_tools():
    names = {
        name
        for name in mcp_server.mcp._tool_manager._tools
        if "attachment" in name
    }
    assert names == {
        "create_attachment",
        "read_attachment",
        "delete_attachment",
    }


@pytest.mark.parametrize(
    "owner_args",
    [
        {},
        {"task_id": "task", "project_id": "project"},
        {"task_id": "task", "epic_id": "epic"},
        {"project_id": "project", "epic_id": "epic"},
    ],
)
def test_create_requires_exactly_one_owner(owner_args):
    with pytest.raises(ValueError, match="exactly one"):
        asyncio.run(mcp_server.create_attachment(
            filename="x.txt", content="x", **owner_args,
        ))


@pytest.mark.parametrize(
    "read_args",
    [
        {},
        {"attachment_id": "attachment", "task_id": "task"},
        {"task_id": "task", "project_id": "project"},
        {"project_id": "project", "epic_id": "epic"},
    ],
)
def test_read_requires_exactly_one_identifier(read_args):
    with pytest.raises(ValueError, match="exactly one"):
        asyncio.run(mcp_server.read_attachment(**read_args))


@pytest.mark.parametrize("owner_kind", ["task", "project", "epic"])
def test_member_can_create_read_and_delete_each_scope(owner_kind):
    project, task, epic = _scenario()
    owners = {"task": task, "project": project, "epic": epic}
    owner = owners[owner_kind]
    owner_args = {f"{owner_kind}_id": owner["id"]}

    with _actor("alice"):
        created = asyncio.run(mcp_server.create_attachment(
            filename=f"{owner_kind}.txt",
            content=f"{owner_kind} body",
            content_type="text/plain",
            **owner_args,
        ))
        listed = asyncio.run(mcp_server.read_attachment(**owner_args))
        read = asyncio.run(mcp_server.read_attachment(
            attachment_id=created["id"],
        ))
        deleted = asyncio.run(mcp_server.delete_attachment(created["id"]))

    assert created[f"{owner_kind}_id"] == owner["id"]
    assert [row["id"] for row in listed] == [created["id"]]
    assert read["content"] == f"{owner_kind} body"
    assert deleted is True


@pytest.mark.parametrize("owner_kind", ["task", "project", "epic"])
def test_non_member_cannot_create_or_list_by_owner_id(owner_kind):
    project, task, epic = _scenario()
    owners = {"task": task, "project": project, "epic": epic}
    owner_args = {f"{owner_kind}_id": owners[owner_kind]["id"]}

    with _actor("mallory"), pytest.raises(
        PermissionError,
        match="Project resource not found or access denied",
    ):
        asyncio.run(mcp_server.create_attachment(
            filename="stolen.txt", content="stolen", **owner_args,
        ))

    with _actor("mallory"), pytest.raises(
        PermissionError,
        match="Project resource not found or access denied",
    ):
        asyncio.run(mcp_server.read_attachment(**owner_args))


@pytest.mark.parametrize("owner_kind", ["task", "project", "epic"])
def test_non_member_cannot_read_or_delete_by_attachment_id(owner_kind):
    project, task, epic = _scenario()
    owners = {"task": task, "project": project, "epic": epic}
    owner_args = {f"{owner_kind}_id": owners[owner_kind]["id"]}
    with _actor("alice"):
        created = asyncio.run(mcp_server.create_attachment(
            filename="secret.txt", content="secret", **owner_args,
        ))

    with _actor("mallory"), pytest.raises(
        PermissionError,
        match="Project resource not found or access denied",
    ):
        asyncio.run(mcp_server.read_attachment(attachment_id=created["id"]))

    with _actor("mallory"), pytest.raises(
        PermissionError,
        match="Project resource not found or access denied",
    ):
        asyncio.run(mcp_server.delete_attachment(created["id"]))


def test_system_wildcard_can_read_and_delete_by_attachment_id():
    project, _, _ = _scenario()
    with _actor("alice"):
        created = asyncio.run(mcp_server.create_attachment(
            project_id=project["id"], filename="admin.txt", content="ok",
            content_type="text/plain",
        ))

    with _actor("system"):
        read = asyncio.run(mcp_server.read_attachment(
            attachment_id=created["id"],
        ))
        deleted = asyncio.run(mcp_server.delete_attachment(created["id"]))

    assert read["content"] == "ok"
    assert deleted is True
