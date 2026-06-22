"""AP-190: one Run per (agent, task), reused across turns.

`get_or_create_task_run` creates the row on the first dispatch and reuses the
SAME row on every later turn — resetting it to RUNNING and clearing the prior
turn's terminal verdict, while keeping the resume handle (`session_id`) and a
sticky `is_work`.
"""

from __future__ import annotations

import pytest

import backend.db as bdb
from backend.forge import runs as forge_runs
from backend.forge.models import Agent, Run, RunStatus, RunOutcome
from backend.models import Project, Task, Status


@pytest.fixture(autouse=True)
def test_db(pg):
    """Shared ephemeral-Postgres harness. forge_runs.get_or_create_task_run
    takes a db session, so we yield the real SessionLocal. Run's agent_id /
    task_id / project_id are FKs (Postgres enforces them) — the literal
    "a1"/"a2"/"t1"/"p1" handles the tests pass need backing rows."""
    with bdb.privileged(), bdb.SessionLocal() as db:
        status_id = db.query(Status).first().id
        db.add(Agent(id="a1", org_id=pg.org_id, name="A1", executor_type="cli"))
        db.add(Agent(id="a2", org_id=pg.org_id, name="A2", executor_type="cli"))
        db.add(Project(id="p1", org_id=pg.org_id, name="P1"))
        db.add(Task(id="t1", org_id=pg.org_id, project_id="p1", title="T1",
                    status_id=status_id))
        db.commit()
    yield bdb.SessionLocal


def _count_runs(db, agent_id, task_id):
    return (db.query(Run)
              .filter(Run.agent_id == agent_id, Run.task_id == task_id)
              .count())


def test_first_call_creates_then_reuses(test_db):
    db = test_db()
    rid1 = forge_runs.get_or_create_task_run(
        db, agent_id="a1", task_id="t1", project_id="p1",
        initial_prompt="turn one", worktree_branch="b1")
    db.commit()
    # Second turn — same (agent, task): must reuse the SAME row.
    rid2 = forge_runs.get_or_create_task_run(
        db, agent_id="a1", task_id="t1", project_id="p1",
        initial_prompt="turn two")
    db.commit()
    assert rid1 == rid2
    assert _count_runs(db, "a1", "t1") == 1
    db.close()


def test_reuse_resets_terminal_verdict_but_keeps_session_and_is_work(test_db):
    db = test_db()
    rid = forge_runs.get_or_create_task_run(
        db, agent_id="a1", task_id="t1", project_id="p1")
    # Simulate the first turn finishing with durable work + a resume handle.
    run = db.query(Run).filter(Run.id == rid).first()
    run.status = RunStatus.COMPLETED
    run.outcome = RunOutcome.SUCCEEDED
    run.error = "n/a"
    run.is_work = True
    run.session_id = "sess-123"
    db.commit()

    forge_runs.get_or_create_task_run(
        db, agent_id="a1", task_id="t1", project_id="p1")
    db.commit()
    run = db.query(Run).filter(Run.id == rid).first()
    assert run.status == RunStatus.RUNNING      # reset for the new turn
    assert run.outcome is None and run.error is None  # prior verdict cleared
    assert run.is_work is True                  # sticky
    assert run.session_id == "sess-123"         # resume handle preserved
    db.close()


def test_distinct_agents_get_distinct_runs(test_db):
    db = test_db()
    r_a = forge_runs.get_or_create_task_run(
        db, agent_id="a1", task_id="t1", project_id="p1")
    r_b = forge_runs.get_or_create_task_run(
        db, agent_id="a2", task_id="t1", project_id="p1")
    db.commit()
    assert r_a != r_b   # per (agent, task), not per task
    db.close()
