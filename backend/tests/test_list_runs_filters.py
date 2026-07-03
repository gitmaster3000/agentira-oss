"""Regression test for the prod crash where GET /api/forge/runs?status=<bad>
hit Postgres with a value the runstatus/runoutcome enums don't have, raising
an unhandled psycopg2.errors.InvalidTextRepresentation instead of a clean 400.

Also covers the `outcome` filter added alongside the fix: the frontend's
"waiting on a human" queries were sending status='waiting_human', a value
that was never a real RunStatus — the actual signal for that is
Run.outcome == 'needs_input'.
"""

from __future__ import annotations

import pytest

from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime, RuntimeStatus
from backend import services as core_services


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg


def _make_run(outcome=None, *, daemon_id):
    with forge_services._session() as db:
        rt = ForgeRuntime(daemon_id=daemon_id, provider="claude", binary_path="/tmp/c",
                          status=RuntimeStatus.ONLINE)
        db.add(rt); db.commit(); rt_id = rt.id
    project = core_services.create_project("Filter Test", actor="system")
    agent = forge_services.create_agent(name=f"Agent-{daemon_id}", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(agent_id=agent["id"], project_id=project["id"])
    if outcome:
        forge_services.finish_run(run["id"], outcome=outcome)
    return run["id"]


def test_list_runs_rejects_unknown_status():
    with pytest.raises(ValueError):
        forge_services.list_runs(status="waiting_human")


def test_list_runs_accepts_known_status():
    assert forge_services.list_runs(status="running") == []


def test_list_runs_rejects_unknown_outcome():
    with pytest.raises(ValueError):
        forge_services.list_runs(outcome="waiting_human")


def test_list_runs_filters_by_needs_input_outcome():
    waiting_id = _make_run(outcome="needs_input", daemon_id="d1")
    _make_run(outcome="succeeded", daemon_id="d2")

    waiting = forge_services.list_runs(outcome="needs_input")
    assert [r["id"] for r in waiting] == [waiting_id]
