"""Dispatch refuses agents that cannot reach the project board.

An agent with no profile / API key gets no Agentira MCP; an agent that is not a
project member is rejected by the board API. Either way its run cannot read the
task, comment or finish_run, so dispatch says so up front in plain words.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

import backend.db as db_mod
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import Agent, ForgeRuntime, RuntimeStatus
from backend.models import Profile, ProjectMember


@pytest.fixture(autouse=True)
def org_db(pg):
    yield


class _FakeHub:
    def __init__(self):
        self.calls: list[dict] = []

    async def dispatch_trigger(self, **kwargs):
        self.calls.append(kwargs)


def _drive(fn):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = fn()
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True))
        return result
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _runtime_id():
    db = db_mod.SessionLocal()
    rt = ForgeRuntime(daemon_id="d", provider="claude",
                      binary_path="/tmp/claude", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rid = rt.id
    db.close()
    return rid


def _project_task():
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "Build it", actor="system")
    return project["id"], task["id"]


def _join(project_id, profile_id):
    db = db_mod.SessionLocal()
    db.add(ProjectMember(project_id=project_id, profile_id=profile_id))
    db.commit()
    db.close()


def _dispatch(task_id, agent_id):
    run = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent_id))
    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        out = _drive(lambda: forge_services.dispatch_pending_run(
            run_id=run["id"]))
    return out, fake


def test_agent_without_profile_is_refused_in_plain_words():
    project_id, task_id = _project_task()
    db = db_mod.SessionLocal()
    a = Agent(name="planner", executor_type="cli", runtime_id=_runtime_id())
    db.add(a)
    db.commit()
    agent_id = a.id
    db.close()

    out, fake = _dispatch(task_id, agent_id)

    assert out["error"] == (
        "planner cannot reach this project board — it has no Agentira "
        "identity. Give it a profile with an API key.")
    assert fake.calls == []


def test_agent_without_api_key_is_refused():
    project_id, task_id = _project_task()
    agent = forge_services.create_agent(name="scribe", executor_type="cli",
                                        runtime_id=_runtime_id())
    db = db_mod.SessionLocal()
    db.get(Profile, agent["profile_id"]).api_key = None
    db.commit()
    db.close()
    _join(project_id, agent["profile_id"])

    out, fake = _dispatch(task_id, agent["id"])

    assert "scribe cannot reach this project board" in out["error"]
    assert "API key" in out["error"]
    assert fake.calls == []


def test_non_member_agent_is_refused_in_plain_words():
    project_id, task_id = _project_task()
    agent = forge_services.create_agent(name="Docs", executor_type="cli",
                                        runtime_id=_runtime_id())

    out, fake = _dispatch(task_id, agent["id"])

    assert out["error"] == (
        "Docs cannot reach this project board — add it as a member of the "
        "project.")
    assert fake.calls == []


def test_member_agent_with_identity_dispatches():
    project_id, task_id = _project_task()
    agent = forge_services.create_agent(name="Dev", executor_type="cli",
                                        runtime_id=_runtime_id())
    _join(project_id, agent["profile_id"])

    out, fake = _dispatch(task_id, agent["id"])

    assert "error" not in out
    assert len(fake.calls) == 1


def test_agent_card_flags_missing_identity_and_membership():
    project_id, _ = _project_task()
    agent = forge_services.create_agent(name="Docs", executor_type="cli",
                                        runtime_id=_runtime_id())
    db = db_mod.SessionLocal()
    db.get(Agent, agent["id"]).default_project_id = project_id
    db.commit()
    db.close()

    card = forge_services.get_agent(agent["id"])["board_access"]
    assert card["ok"] is False
    assert card["problems"] == [
        "Docs cannot reach this project board — add it as a member of the "
        "project."]

    _join(project_id, agent["profile_id"])
    assert forge_services.get_agent(agent["id"])["board_access"] == {
        "ok": True, "problems": []}


def test_rest_dispatch_400_and_agent_payload_over_http(seed_admin):
    from fastapi.testclient import TestClient
    from backend.rest_api import app

    _, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    project_id, task_id = _project_task()
    agent = forge_services.create_agent(name="Docs", executor_type="cli",
                                        runtime_id=_runtime_id())
    run = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent["id"]))

    res = c.post(f"/api/forge/runs/{run['id']}/dispatch", json={})
    assert res.status_code == 400
    assert res.json()["detail"] == (
        "Docs cannot reach this project board — add it as a member of the "
        "project.")

    db = db_mod.SessionLocal()
    db.get(Agent, agent["id"]).default_project_id = project_id
    db.commit()
    db.close()
    card = c.get(f"/api/forge/agents/{agent['id']}").json()["board_access"]
    assert card["ok"] is False and len(card["problems"]) == 1
