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


def test_mcp_get_roadmap_forwards_filters(monkeypatch):
    captured = {}
    monkeypatch.setattr(services, "authorize_project_access", lambda *_args: None)

    def fake_get_roadmap(project_id, **kwargs):
        captured.update(project_id=project_id, **kwargs)
        return {"epics": []}

    monkeypatch.setattr(services, "get_roadmap", fake_get_roadmap)

    result = asyncio.run(mcp_server.get_roadmap(
        "project-1",
        epic_ids=["epic-1", "epic-2"],
        tag="focus",
        milestone_id="milestone-1",
        status="todo",
        fields="compact",
    ))

    assert result == {"epics": []}
    assert captured == {
        "project_id": "project-1",
        "group_by": "epic",
        "epic_ids": ["epic-1", "epic-2"],
        "tag": "focus",
        "milestone_id": "milestone-1",
        "status": "todo",
        "fields": "compact",
        "include_done": False,
    }


def test_mcp_get_roadmap_hides_done_by_default_but_can_include_it(monkeypatch):
    calls = []
    monkeypatch.setattr(services, "authorize_project_access", lambda *_args: None)
    monkeypatch.setattr(
        services, "get_roadmap", lambda project_id, **kw: calls.append(kw) or {},
    )

    asyncio.run(mcp_server.get_roadmap("project-1"))
    asyncio.run(mcp_server.get_roadmap("project-1", include_done=True))

    assert [c["include_done"] for c in calls] == [False, True]
