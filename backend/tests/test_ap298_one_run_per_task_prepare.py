"""AP-298: one run per (agent, task) on the explicit scheduled path.

Before AP-298, every call to ``prepare_task_run`` created a fresh READY run,
so a task could accumulate multiple "ready" runs for the same agent. The
prepare path now mirrors the chat get-or-create discipline: it reuses the
single ``task.scheduled`` run for an (agent, task) — re-preparing a finished
run in place and never stacking a duplicate.

Unlike the legacy AP-112 fixtures, this wires real org context (the tenancy
boundary stamps ``org_id`` on flush), so the service runs end to end.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import backend.db as db_mod
from backend.db import Base, set_current_org
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    ForgeRuntime, RuntimeStatus, Run, RunStatus, RunOutcome,
)


@pytest.fixture(autouse=True)
def org_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    # Route the real SessionLocal (with the org-stamping event listeners) at
    # the in-memory engine for both the request and privileged binds.
    with patch.object(db_mod, "engine", engine), \
         patch.object(db_mod, "app_engine", engine):
        from backend.db import SessionLocal
        from backend.models import Org
        db = SessionLocal()
        core_services._seed_defaults(db)
        db.add(Org(id="orgtest00000", name="Test Org"))
        db.commit()
        db.close()
        set_current_org("orgtest00000")
        try:
            yield
        finally:
            set_current_org(None)


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


def _mk_task_agent():
    db = db_mod.SessionLocal()
    rt = ForgeRuntime(daemon_id="d", provider="claude",
                      binary_path="/tmp/claude", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "Build it", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    return task["id"], agent["id"]


def _runs(agent_id, task_id):
    db = db_mod.SessionLocal()
    n = (db.query(Run)
           .filter(Run.agent_id == agent_id, Run.task_id == task_id)
           .count())
    db.close()
    return n


def test_second_prepare_reuses_the_same_run():
    task_id, agent_id = _mk_task_agent()
    a = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent_id))
    b = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent_id))
    assert a["id"] == b["id"]
    assert _runs(agent_id, task_id) == 1


def test_prepare_reuses_terminal_run_and_clears_verdict():
    task_id, agent_id = _mk_task_agent()
    a = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent_id))
    db = db_mod.SessionLocal()
    r = db.query(Run).filter(Run.id == a["id"]).first()
    r.status = RunStatus.FAILED
    r.outcome = RunOutcome.FAILED
    r.error = "boom"
    db.commit()
    db.close()

    b = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent_id))
    assert b["id"] == a["id"]
    assert b["status"] == "ready"
    assert _runs(agent_id, task_id) == 1
    db = db_mod.SessionLocal()
    r = db.query(Run).filter(Run.id == a["id"]).first()
    assert r.outcome is None and r.error is None
    db.close()


def test_prepare_returns_live_run_untouched():
    task_id, agent_id = _mk_task_agent()
    a = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent_id))
    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        _drive(lambda: forge_services.dispatch_pending_run(run_id=a["id"]))

    b = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent_id))
    assert b["id"] == a["id"]
    assert b["status"] == "running"
    assert _runs(agent_id, task_id) == 1
