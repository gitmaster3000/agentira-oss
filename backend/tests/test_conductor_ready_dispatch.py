"""Loop v1 C1: a READY run (prepared on assignment, never started) must not
block the Conductor from dispatching the task to its own agent."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from backend import services as core_services
from backend.forge import conductor, services as forge_services
from backend.forge.models import Agent, ForgeRuntime, Run, RunStatus


@pytest.fixture(autouse=True)
def _db(pg):
    yield pg


def _managed_agent_with_ready_task() -> tuple[str, str, str]:
    """Conductor-managed agent + an assigned todo task whose only run is a
    READY draft (what assignment creates). Returns (agent_id, task_id,
    project_id)."""
    bot = core_services.create_service_account("impl-ready")
    proj = core_services.create_project("ReadyProj")
    from backend.models import Profile, Status, Task
    with forge_services._session() as db:
        rt = ForgeRuntime(id=uuid.uuid4().hex[:12], daemon_id="d1",
                          provider="claude", binary_path="/bin/claude",
                          status="online")
        db.add(rt)
        prof = db.get(Profile, bot["id"])
        prof.default_project_id = proj["id"]
        prof.conductor_enabled = True
        prof.runtime_id = rt.id
        agent = Agent(id=bot["id"], profile_id=bot["id"], name="impl-ready",
                      executor_type="http", model="", runtime_id=rt.id)
        db.add(agent)
        todo = db.query(Status).filter(Status.name == "todo").first()
        t = Task(project_id=proj["id"], key="RP-1", title="t",
                 description="", status_id=todo.id, assignee="impl-ready")
        db.add(t)
        db.flush()
        db.add(Run(agent_id=agent.id, task_id=t.id, project_id=proj["id"],
                   status=RunStatus.READY, trigger_event="task.scheduled"))
        db.commit()
        return agent.id, t.id, proj["id"]


def test_ready_run_does_not_block_pick():
    agent_id, task_id, project_id = _managed_agent_with_ready_task()
    picked = conductor.pick_next_unblocked(project_id=project_id, agent_id=agent_id)
    assert picked is not None and picked.id == task_id


def test_tick_dispatches_task_with_ready_run():
    agent_id, task_id, _ = _managed_agent_with_ready_task()
    with patch.object(forge_services, "schedule_task_run",
                      return_value={"run_id": "r1"}) as sched:
        out = conductor.run_tick()
    sched.assert_called_once_with(task_id=task_id, agent_id=agent_id)
    assert {"agent": agent_id, "task": task_id, "run_id": "r1"} in out["dispatched"]


def test_tick_leaves_a_dispatch_line_on_the_task():
    agent_id, task_id, _ = _managed_agent_with_ready_task()
    with patch.object(forge_services, "schedule_task_run",
                      return_value={"run_id": "r1"}):
        conductor.run_tick()
    rows = core_services.get_activity(task_id)
    assert any("dispatched this task to **impl-ready**" in (a.get("detail") or "")
               for a in rows)
