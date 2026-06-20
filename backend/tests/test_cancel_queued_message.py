"""Cancel a queued message before it dispatches (AP-287).

msg_queue.remove() deletes one queued row by id, scoped to its (agent, scope)
so a stale id from another conversation can't delete it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend.forge import msg_queue
from backend.forge import services as forge_services


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.forge.msg_queue.SessionLocal", TestSession):
        yield


def test_remove_cancels_only_the_targeted_message():
    a, scope = "agent1", "task:t1"
    q1 = msg_queue.enqueue(agent_id=a, scope_key=scope, content="first")
    q2 = msg_queue.enqueue(agent_id=a, scope_key=scope, content="second")

    assert len(msg_queue.list_for_scope(agent_id=a, scope_key=scope)) == 2

    assert msg_queue.remove(queued_id=q1, agent_id=a, scope_key=scope) is True
    remaining = msg_queue.list_for_scope(agent_id=a, scope_key=scope)
    assert [r["id"] for r in remaining] == [q2]


def test_remove_is_scoped_to_conversation():
    q = msg_queue.enqueue(agent_id="agent1", scope_key="task:t1", content="x")
    # Right id, wrong scope → no delete.
    assert msg_queue.remove(queued_id=q, agent_id="agent1", scope_key="task:OTHER") is False
    assert msg_queue.remove(queued_id=q, agent_id="OTHER", scope_key="task:t1") is False
    assert len(msg_queue.list_for_scope(agent_id="agent1", scope_key="task:t1")) == 1


def test_service_wrapper_reports_removed():
    q = msg_queue.enqueue(agent_id="agent1", scope_key="task:t1", content="x")
    assert forge_services.cancel_queued_message(
        agent_id="agent1", scope_key="task:t1", queued_id=q) == {"ok": True}
    assert forge_services.cancel_queued_message(
        agent_id="agent1", scope_key="task:t1", queued_id="nope") == {"ok": False}
