"""AP-112: the run state machine — prepare → READY → dispatch → RUNNING.

Clicking "Run" on a task no longer auto-starts the agent. It prepares a
Run: the prompt is built from the task and persisted, the run lands in
READY, and the user reviews/edits the prompt before pressing Start.
`schedule_task_run` keeps the no-edit auto-start path for the Conductor
and webhooks.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime, RuntimeStatus, Run, RunStatus


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _seed_runtime(TestSession) -> str:
    db = TestSession()
    rt = ForgeRuntime(daemon_id="test-daemon", provider="claude",
                      binary_path="/tmp/claude", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    return rt_id


class _FakeHub:
    def __init__(self):
        self.calls: list[dict] = []

    async def dispatch_trigger(self, **kwargs):
        self.calls.append(kwargs)


def _drive(fn):
    """Run fn() inside a fresh event loop so its dispatch coroutine fires."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = fn()
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        return result
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _mk_task_agent(TestSession):
    rt_id = _seed_runtime(TestSession)
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "Build the thing",
                                     actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    return task["id"], agent["id"]


def test_prepare_creates_ready_run_without_dispatching(test_db):
    """prepare_task_run lands a READY run with the prompt persisted and
    fires NO trigger — the agent is not started."""
    task_id, agent_id = _mk_task_agent(test_db)

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        result = _drive(lambda: forge_services.prepare_task_run(
            task_id=task_id, agent_id=agent_id))

    assert fake.calls == [], "prepare must not dispatch"
    assert result["status"] == "ready"
    assert "Build the thing" in result["initial_prompt"]
    assert "finish_run" in result["initial_prompt"]
    # The {run_id} placeholder is substituted with the real id.
    assert "{run_id}" not in result["initial_prompt"]
    assert result["id"] in result["initial_prompt"]


def test_dispatch_pending_run_starts_a_ready_run(test_db):
    """dispatch_pending_run fires exactly one trigger and flips the run
    READY → RUNNING."""
    task_id, agent_id = _mk_task_agent(test_db)
    prepared = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent_id))
    run_id = prepared["id"]

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        _drive(lambda: forge_services.dispatch_pending_run(run_id=run_id))

    assert len(fake.calls) == 1
    assert fake.calls[0]["run_id"] == run_id
    assert forge_services.get_run(run_id)["status"] == "running"


def test_dispatch_honours_edited_prompt(test_db):
    """A prompt override passed to dispatch is what the agent receives and
    is persisted back onto the run."""
    task_id, agent_id = _mk_task_agent(test_db)
    prepared = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent_id))
    run_id = prepared["id"]

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        _drive(lambda: forge_services.dispatch_pending_run(
            run_id=run_id, prompt_override="do exactly this instead"))

    assert fake.calls[0]["prompt"] == "do exactly this instead"
    assert forge_services.get_run(run_id)["initial_prompt"] == \
        "do exactly this instead"


def test_dispatch_rejects_already_running_run(test_db):
    """Only READY/PENDING runs are dispatchable — a RUNNING run can't be
    re-dispatched."""
    task_id, agent_id = _mk_task_agent(test_db)
    prepared = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent_id))
    run_id = prepared["id"]
    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        _drive(lambda: forge_services.dispatch_pending_run(run_id=run_id))
        result = _drive(lambda: forge_services.dispatch_pending_run(run_id=run_id))

    assert "error" in result
    assert len(fake.calls) == 1, "second dispatch must not fire a trigger"


def test_discard_deletes_a_ready_run(test_db):
    """discard removes the READY row entirely."""
    task_id, agent_id = _mk_task_agent(test_db)
    prepared = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent_id))
    run_id = prepared["id"]

    result = forge_services.discard_pending_run(run_id=run_id)
    assert result.get("ok") is True
    assert forge_services.get_run(run_id) is None


def test_discard_rejects_a_running_run(test_db):
    """A RUNNING run can't be discarded — cancel is the terminal path."""
    task_id, agent_id = _mk_task_agent(test_db)
    prepared = _drive(lambda: forge_services.prepare_task_run(
        task_id=task_id, agent_id=agent_id))
    run_id = prepared["id"]
    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        _drive(lambda: forge_services.dispatch_pending_run(run_id=run_id))

    result = forge_services.discard_pending_run(run_id=run_id)
    assert "error" in result
    assert forge_services.get_run(run_id) is not None


def test_schedule_task_run_still_auto_starts(test_db):
    """The Conductor/webhook path: schedule_task_run = prepare + dispatch
    in one call, with no READY pit-stop visible to the caller."""
    task_id, agent_id = _mk_task_agent(test_db)

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        result = _drive(lambda: forge_services.schedule_task_run(
            task_id=task_id, agent_id=agent_id))

    assert len(fake.calls) == 1
    run_id = result["run_id"]
    assert forge_services.get_run(run_id)["status"] == "running"


def test_prepare_unknown_task_errors(test_db):
    _, agent_id = _mk_task_agent(test_db)
    result = forge_services.prepare_task_run(
        task_id=uuid.uuid4().hex, agent_id=agent_id)
    assert "error" in result
