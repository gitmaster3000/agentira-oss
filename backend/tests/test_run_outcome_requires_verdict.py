"""A clean process exit is NOT an agent verdict.

Found live: a qwen/openclaw run exited 0 without ever calling finish_run
(the board tools were not in its toolset) and the run was stamped
outcome=succeeded with an empty summary — manufactured green. `outcome`
must come only from an explicit finish_run; absent that the run is
COMPLETED with outcome=None ("process exited without a verdict").
"""

from __future__ import annotations

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    ForgeRuntime, Run, RunOutcome, RunStatus, RuntimeStatus,
)


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg.SessionLocal


def _setup() -> dict:
    with bdb.SessionLocal() as db:
        rt = ForgeRuntime(daemon_id="d", provider="openclaw", binary_path="/tmp/o",
                          status=RuntimeStatus.ONLINE)
        db.add(rt)
        db.commit()
        rt_id = rt.id
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "T", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    return {"task_id": task["id"], "agent_id": agent["id"]}


def _running_run(s: dict) -> str:
    r = forge_services.prepare_task_run(task_id=s["task_id"], agent_id=s["agent_id"])
    with forge_services._session() as db:
        db.query(Run).filter(Run.id == r["id"]).update({"status": RunStatus.RUNNING})
        db.commit()
    return r["id"]


def _run(run_id: str) -> Run:
    with forge_services._session() as db:
        return db.query(Run).filter(Run.id == run_id).first()


def test_clean_exit_without_finish_run_is_not_succeeded(test_db):
    s = _setup()
    run_id = _running_run(s)
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t", run_id=run_id, success=True,
    )
    r = _run(run_id)
    assert r.status == RunStatus.COMPLETED
    assert r.outcome != RunOutcome.SUCCEEDED, (
        "process exit 0 without finish_run must not be stamped succeeded"
    )
    assert r.outcome is None


def test_explicit_finish_run_verdict_is_preserved(test_db):
    """The verdict path still works: an outcome set before the process
    exits is what the run keeps."""
    s = _setup()
    run_id = _running_run(s)
    with forge_services._session() as db:
        db.query(Run).filter(Run.id == run_id).update(
            {"outcome": RunOutcome.SUCCEEDED, "summary": "did the thing"})
        db.commit()
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t", run_id=run_id, success=True,
    )
    assert _run(run_id).outcome == RunOutcome.SUCCEEDED


def test_failed_exit_without_verdict_is_still_failed(test_db):
    s = _setup()
    run_id = _running_run(s)
    forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t", run_id=run_id, success=False,
        error="boom",
    )
    assert _run(run_id).outcome == RunOutcome.FAILED
