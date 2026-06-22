"""Chat into a failed-run task is just a chat turn — NO auto-retry.

The old AP-120 auto-retry (chat into a failed run → schedule a fresh
task.scheduled run) turned plain comments/chats into runs marked is_work=True.
Removed: a failed run is retried only via the explicit Retry button.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    Agent, Run, RunStatus, RunOutcome, AgentMessage, MessageRole,
)


@pytest.fixture(autouse=True)
def _harness(pg):
    """Shared ephemeral-Postgres harness (org context pinned by `pg`)."""
    yield


def _mk_agent_task():
    bot = core_services.create_service_account("bot1")
    proj = core_services.create_project("P")
    from backend.models import Task, Status
    with forge_services._session() as db:
        a = Agent(id=bot["id"], profile_id=bot["id"], name="bot1",
                  executor_type="http", model="")
        db.add(a)
        status = db.query(Status).first()
        t = Task(id=uuid.uuid4().hex[:12], project_id=proj["id"],
                 key="P-1", title="T", description="",
                 status_id=status.id if status else None)
        db.add(t)
        db.commit()
        return a.id, t.id


def _add_run(agent_id, task_id, *, status, outcome=None):
    rid = uuid.uuid4().hex[:12]
    with forge_services._session() as db:
        db.add(Run(id=rid, agent_id=agent_id, task_id=task_id,
                   status=status, outcome=outcome))
        db.commit()
    return rid


def test_chat_into_failed_run_does_not_auto_retry():
    """A message into a task whose last run FAILED must NOT auto-schedule a
    retry run. Auto-retry turned plain comments/chats into task.scheduled runs
    (stamped is_work=True), so a talk-only reply looked like work. Retrying a
    failed run is an explicit action now; chat is just a chat turn."""
    agent_id, task_id = _mk_agent_task()
    _add_run(agent_id, task_id, status=RunStatus.FAILED,
             outcome=RunOutcome.FAILED)
    calls = []

    def fake_schedule(*, task_id, agent_id, extra_context=""):
        calls.append({"task": task_id, "ctx": extra_context})
        return {"ok": True, "run_id": "new-run-1"}

    with patch.object(forge_services, "schedule_task_run", fake_schedule), \
         patch("backend.forge.services._dispatch_coro", lambda c: None):
        result = forge_services.send_runtime_message(
            agent_id, content="please reply", scope_key=f"task:{task_id}")

    assert calls == [], "must not auto-schedule a retry run"
    assert "retried_run_id" not in result


def test_in_flight_run_blocks_retry():
    """If a run is still in flight, chatting does NOT double-dispatch."""
    agent_id, task_id = _mk_agent_task()
    _add_run(agent_id, task_id, status=RunStatus.FAILED)   # old, failed
    _add_run(agent_id, task_id, status=RunStatus.RUNNING)  # current
    calls = []
    with patch.object(forge_services, "schedule_task_run",
                      lambda **kw: (calls.append(kw), {"run_id": "x"})[1]):
        forge_services.send_runtime_message(
            agent_id, content="hi", scope_key=f"task:{task_id}")
    assert calls == [], "must not schedule a retry while a run is in flight"


def test_no_runs_does_not_retry():
    """A task with no runs at all is a normal chat, not a retry."""
    agent_id, task_id = _mk_agent_task()
    calls = []
    with patch.object(forge_services, "schedule_task_run",
                      lambda **kw: (calls.append(kw), {"run_id": "x"})[1]):
        forge_services.send_runtime_message(
            agent_id, content="hello", scope_key=f"task:{task_id}")
    assert calls == []
