"""AP-120: chatting into a task whose last run FAILED schedules a fresh
run (a retry) instead of a bare chat turn, and tells the user.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    Agent, Run, RunStatus, RunOutcome, AgentMessage, MessageRole,
)


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.runs.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _mk_agent_task():
    bot = core_services.create_service_account("bot1")
    proj = core_services.create_project("P")
    from backend.models import Task, Status
    with forge_services._session() as db:
        a = Agent(id=bot["id"], profile_id=bot["id"], name="bot1",
                  executor_type="http", model="")
        db.add(a)
        status = db.query(Status).first()
        t = Task(id=uuid.uuid4().hex, project_id=proj["id"],
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


def test_chat_into_failed_run_schedules_new_run():
    agent_id, task_id = _mk_agent_task()
    _add_run(agent_id, task_id, status=RunStatus.FAILED,
             outcome=RunOutcome.FAILED)
    calls = []

    def fake_schedule(*, task_id, agent_id, extra_context=""):
        calls.append({"task": task_id, "ctx": extra_context})
        return {"ok": True, "run_id": "new-run-1"}

    with patch.object(forge_services, "schedule_task_run", fake_schedule):
        result = forge_services.send_runtime_message(
            agent_id, content="please retry, fix the import",
            scope_key=f"task:{task_id}")

    assert result.get("retried_run_id") == "new-run-1"
    assert len(calls) == 1
    assert "fix the import" in calls[0]["ctx"]

    # A SYSTEM message tells the user a new run started.
    with forge_services._session() as db:
        sys_msgs = (db.query(AgentMessage)
                      .filter(AgentMessage.scope_key == f"task:{task_id}",
                              AgentMessage.role == MessageRole.SYSTEM)
                      .all())
    assert any("new run" in m.content.lower() for m in sys_msgs)


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
