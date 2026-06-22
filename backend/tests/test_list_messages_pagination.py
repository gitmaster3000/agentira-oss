"""list_messages windowed pagination.

Regression: the query ordered ASC + limit, so a scope past `limit` messages
froze on its oldest N and new turns never appeared in the chat view (only in
run-detail, which queries by run_id). list_messages must return the NEWEST
`limit` messages (ascending for display), with offset paging backward into
history.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as fs
from backend.forge.models import (
    Agent, AgentMessage, MessageRole, ForgeRuntime, RuntimeStatus,
)


@pytest.fixture(autouse=True)
def test_db(pg):
    yield bdb.SessionLocal


def _seed_messages(n: int, scope: str = "task:T1") -> str:
    with fs._session() as db:
        rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/c",
                          status=RuntimeStatus.ONLINE)
        db.add(rt); db.commit(); rt_id = rt.id
    agent = fs.create_agent(name="A", executor_type="cli", runtime_id=rt_id)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with fs._session() as db:
        for i in range(n):
            db.add(AgentMessage(
                agent_id=agent["id"], scope_key=scope,
                role=MessageRole.USER, content=f"msg {i}",
                created_at=base + timedelta(minutes=i),
            ))
        db.commit()
    return agent["id"]


def test_returns_newest_limit_in_ascending_order():
    agent_id = _seed_messages(250)
    page = fs.list_messages(agent_id, scope_key="task:T1", limit=80)
    assert len(page) == 80
    # Ascending for display, and the window is the NEWEST 80 (msg 170..249).
    assert page[0]["content"] == "msg 170"
    assert page[-1]["content"] == "msg 249"


def test_offset_pages_backward_into_history():
    agent_id = _seed_messages(250)
    newest = fs.list_messages(agent_id, scope_key="task:T1", limit=80, offset=0)
    older = fs.list_messages(agent_id, scope_key="task:T1", limit=80, offset=80)
    # The older page sits immediately before the newest page, no overlap.
    assert older[-1]["content"] == "msg 169"
    assert newest[0]["content"] == "msg 170"
    older_ids = {m["id"] for m in older}
    newest_ids = {m["id"] for m in newest}
    assert older_ids.isdisjoint(newest_ids)


def test_same_timestamp_burst_pages_without_gap_or_overlap():
    """Tool-step bursts share created_at. Ordering by created_at alone is
    non-deterministic for ties, so offset paging skipped/duplicated rows at
    page boundaries (the "non-continuous" chat scroll). The id tiebreaker
    must give stable, gapless, non-overlapping pages."""
    rt_agent = _seed_messages(0)
    same = datetime(2026, 3, 1, tzinfo=timezone.utc)
    with fs._session() as db:
        for i in range(120):
            db.add(AgentMessage(
                agent_id=rt_agent, scope_key="task:T1",
                role=MessageRole.USER, content=f"burst {i}",
                created_at=same,
            ))
        db.commit()
    p1 = fs.list_messages(rt_agent, scope_key="task:T1", limit=50, offset=0)
    p2 = fs.list_messages(rt_agent, scope_key="task:T1", limit=50, offset=50)
    p3 = fs.list_messages(rt_agent, scope_key="task:T1", limit=50, offset=100)
    seen = [m["id"] for m in (p1 + p2 + p3)]
    # No duplicates across pages and every row surfaces exactly once.
    assert len(seen) == len(set(seen)) == 120


def test_new_message_appears_in_window_past_limit():
    """A scope already past `limit` must still surface a freshly-added turn."""
    agent_id = _seed_messages(200)
    before = fs.list_messages(agent_id, scope_key="task:T1", limit=80)
    assert before[-1]["content"] == "msg 199"
    with fs._session() as db:
        db.add(AgentMessage(
            agent_id=agent_id, scope_key="task:T1", role=MessageRole.USER,
            content="brand new",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        ))
        db.commit()
    after = fs.list_messages(agent_id, scope_key="task:T1", limit=80)
    assert after[-1]["content"] == "brand new", "new turn must appear in the tail"
