"""AP-190: compaction when a task is done.

`compact_task_on_done` promotes the latest run's handoff summary onto the
(agent, task) conversation and drops the native resume handle, so a later
reopen rebuilds from the summary + bounded history instead of the whole
transcript.
"""

from __future__ import annotations

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services  # noqa: F401 — register mappers
from backend.forge.models import Agent, Conversation, Run, RunStatus, RunOutcome


@pytest.fixture
def test_db(pg):
    """Yield the real routing sessionmaker; create FK targets (agent, task)
    so Conversation/Run rows referencing 'a1'/'t1' satisfy Postgres FKs."""
    from backend.models import Task, Status
    proj = core_services.create_project("P")
    with bdb.privileged(), bdb.SessionLocal() as db:
        db.add(Agent(id="a1", profile_id=None, name="bot1",
                     executor_type="http", model="", org_id=pg.org_id))
        status = db.query(Status).first()
        db.add(Task(id="t1", project_id=proj["id"], key="P-1", title="T",
                    description="", status_id=status.id, org_id=pg.org_id))
        db.commit()
    yield bdb.SessionLocal


def _seed(db, *, agent_id="a1", task_id="t1", summary="did the work",
          session="sess-1", rolling=None):
    db.add(Conversation(agent_id=agent_id, scope_key=f"task:{task_id}",
                        runtime_session_id=session, rolling_summary=rolling))
    db.add(Run(agent_id=agent_id, task_id=task_id, status=RunStatus.COMPLETED,
               outcome=RunOutcome.SUCCEEDED, summary=summary, is_work=True))
    db.commit()


def test_promotes_summary_and_drops_session(test_db):
    db = test_db()
    _seed(db)
    db.close()

    from backend.forge import compaction
    n = compaction.compact_task_on_done("t1")
    assert n == 1

    db = test_db()
    conv = db.query(Conversation).filter_by(scope_key="task:t1").first()
    assert conv.rolling_summary == "did the work"   # promoted from the run
    assert conv.runtime_session_id is None           # native resume dropped
    db.close()


def test_keeps_existing_rolling_summary(test_db):
    db = test_db()
    _seed(db, summary="run summary", rolling="already-summarized handoff")
    db.close()

    from backend.forge import compaction
    compaction.compact_task_on_done("t1")

    db = test_db()
    conv = db.query(Conversation).filter_by(scope_key="task:t1").first()
    # A fresher carry-over already existed — don't clobber it with the run's.
    assert conv.rolling_summary == "already-summarized handoff"
    assert conv.runtime_session_id is None
    db.close()


def test_no_conversations_is_a_noop(test_db):
    from backend.forge import compaction
    assert compaction.compact_task_on_done("nonexistent") == 0
    assert compaction.compact_task_on_done("") == 0
