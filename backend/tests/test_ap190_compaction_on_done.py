"""AP-190: compaction when a task is done.

`compact_task_on_done` promotes the latest run's handoff summary onto the
(agent, task) conversation and drops the native resume handle, so a later
reopen rebuilds from the summary + bounded history instead of the whole
transcript.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge.models import Conversation, Run, RunStatus, RunOutcome
from backend.models import Profile, Role


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
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        db.add(Profile(name="admin", role_id=admin_role.id, password_hash=""))
        db.commit()
        db.close()
        yield TestSession


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
