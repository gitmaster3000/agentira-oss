"""Loop v1 C7a: the MCP surface the Conductor needs to run a sprint —
project direction, epic status, tasks created straight into an epic."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

import pytest

from backend import mcp_server, services


@pytest.fixture(autouse=True)
def _db(pg):
    yield pg


@contextmanager
def _as(name: str):
    token = mcp_server.actor_ctx.set(name)
    try:
        yield
    finally:
        mcp_server.actor_ctx.reset(token)


def _project():
    services.create_service_account("planner-x")
    return services.create_project("Dir", actor="planner-x")


def test_mcp_update_project_sets_direction_and_logs():
    proj = _project()
    with _as("planner-x"):
        asyncio.run(mcp_server.update_project(proj["id"], direction_md="Ship Loop v1"))
    assert services.get_project(proj["id"], actor="planner-x")["direction_md"] == "Ship Loop v1"
    acts = services.get_project_activity(proj["id"], actor="planner-x")
    assert any("direction" in (a.get("detail") or "").lower() for a in acts)


def test_mcp_update_epic_sets_status():
    proj = _project()
    epic = services.create_epic(proj["id"], "Loop", actor="planner-x")
    with _as("planner-x"):
        out = asyncio.run(mcp_server.update_epic(epic["id"], status="in_progress"))
    assert out["status"] == "in_progress"


def test_update_epic_rejects_unknown_status():
    proj = _project()
    epic = services.create_epic(proj["id"], "Loop", actor="planner-x")
    with pytest.raises(ValueError):
        services.update_epic(epic["id"], status="todo", actor="planner-x")


def test_mcp_create_task_into_epic():
    proj = _project()
    epic = services.create_epic(proj["id"], "Loop", actor="planner-x")
    with _as("planner-x"):
        t = asyncio.run(mcp_server.create_task(proj["id"], "Step 1", epic_id=epic["id"]))
    assert t["epic_id"] == epic["id"]
