"""AP-190: one Run per (agent, task), reused across turns.

`get_or_create_task_run` creates the row on the first dispatch and reuses the
SAME row on every later turn — resetting it to RUNNING and clearing the prior
turn's terminal verdict, while keeping the resume handle (`session_id`) and a
sticky `is_work`.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import runs as forge_runs
from backend.forge.models import Run, RunStatus, RunOutcome


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.runs.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        # Run rows carry no org_id (not org-scoped), so these tests need no
        # org context — only the unused admin Profile did, so it's gone.
        yield TestSession


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
