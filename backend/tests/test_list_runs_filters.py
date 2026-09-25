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


# AP-509: "Needs you" questions never went away. The Needs-you list asked for
# every run whose outcome was ever needs_input — a verdict nothing clears once
# the question is resolved elsewhere (task finished, or a later run on the task
# picked the work back up, e.g. after a reassignment). `unresolved=True` keeps
# only questions that are still open.

def _task_run(task_id, project_id, *, daemon_id, outcome, started_at, finished_at):
    from backend.forge.models import Run
    with forge_services._session() as db:
        rt = ForgeRuntime(daemon_id=daemon_id, provider="claude", binary_path="/tmp/c",
                          status=RuntimeStatus.ONLINE)
        db.add(rt)
        db.commit()
        rt_id = rt.id
    agent = forge_services.create_agent(name=f"Agent-{daemon_id}", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(agent_id=agent["id"], task_id=task_id,
                                    project_id=project_id)
    forge_services.finish_run(run["id"], outcome=outcome)
    with forge_services._session() as db:
        r = db.get(Run, run["id"])
        r.started_at, r.finished_at = started_at, finished_at
        db.commit()
    return run["id"]


def test_unresolved_hides_questions_resolved_elsewhere():
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    project = core_services.create_project("Needs You", actor="system")
    pid = project["id"]

    open_task = core_services.create_task(pid, "still waiting")
    open_q = _task_run(open_task["id"], pid, daemon_id="q1", outcome="needs_input",
                       started_at=t0, finished_at=t0 + timedelta(minutes=1))

    done_task = core_services.create_task(pid, "finished anyway")
    done_q = _task_run(done_task["id"], pid, daemon_id="q2", outcome="needs_input",
                       started_at=t0, finished_at=t0 + timedelta(minutes=1))
    core_services.move_task(done_task["id"], "done", skip_gates=True)

    handed_task = core_services.create_task(pid, "picked up by another agent")
    handed_q = _task_run(handed_task["id"], pid, daemon_id="q3", outcome="needs_input",
                         started_at=t0, finished_at=t0 + timedelta(minutes=1))
    _task_run(handed_task["id"], pid, daemon_id="q4", outcome="succeeded",
              started_at=t0 + timedelta(minutes=5), finished_at=t0 + timedelta(minutes=9))

    # The raw outcome filter still reports history.
    all_q = {r["id"] for r in forge_services.list_runs(outcome="needs_input")}
    assert all_q == {open_q, done_q, handed_q}

    still_open = forge_services.list_runs(outcome="needs_input", unresolved=True)
    assert [r["id"] for r in still_open] == [open_q]
