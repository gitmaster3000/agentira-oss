"""Cancel a queued message before it dispatches (AP-287).

msg_queue.remove() deletes one queued row by id, scoped to its (agent, scope)
so a stale id from another conversation can't delete it.
"""

from __future__ import annotations

import pytest

import backend.db as bdb
from backend.forge import msg_queue
from backend.forge import services as forge_services
from backend.forge.models import Agent


@pytest.fixture
def agent1(pg):
    """A real agent row — forge_queued_messages.agent_id FKs forge_agents.id,
    which Postgres enforces, so the conversation needs a backing agent."""
    with bdb.privileged(), bdb.SessionLocal() as db:
        a = Agent(org_id=pg.org_id, name="agent1", executor_type="cli")
        db.add(a)
        db.commit()
        return a.id


def test_remove_cancels_only_the_targeted_message(agent1):
    a, scope = agent1, "task:t1"
    q1 = msg_queue.enqueue(agent_id=a, scope_key=scope, content="first")
    q2 = msg_queue.enqueue(agent_id=a, scope_key=scope, content="second")

    assert len(msg_queue.list_for_scope(agent_id=a, scope_key=scope)) == 2

    assert msg_queue.remove(queued_id=q1, agent_id=a, scope_key=scope) is True
    remaining = msg_queue.list_for_scope(agent_id=a, scope_key=scope)
    assert [r["id"] for r in remaining] == [q2]


def test_remove_is_scoped_to_conversation(agent1):
    q = msg_queue.enqueue(agent_id=agent1, scope_key="task:t1", content="x")
    # Right id, wrong scope → no delete.
    assert msg_queue.remove(queued_id=q, agent_id=agent1, scope_key="task:OTHER") is False
    assert msg_queue.remove(queued_id=q, agent_id="OTHER", scope_key="task:t1") is False
    assert len(msg_queue.list_for_scope(agent_id=agent1, scope_key="task:t1")) == 1


def test_service_wrapper_reports_removed(agent1):
    q = msg_queue.enqueue(agent_id=agent1, scope_key="task:t1", content="x")
    assert forge_services.cancel_queued_message(
        agent_id=agent1, scope_key="task:t1", queued_id=q) == {"ok": True}
    assert forge_services.cancel_queued_message(
        agent_id=agent1, scope_key="task:t1", queued_id="nope") == {"ok": False}
