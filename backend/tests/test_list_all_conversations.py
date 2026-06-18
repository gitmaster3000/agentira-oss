"""list_all_conversations: the global /chat list aggregating every agent's chats.

Backs GET /forge/chats — one row per (agent, scope_key), newest first, with
agent name and a last-message preview so the frontend can render the chat
picker without one call per agent.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.models import Org
from backend.forge import services as fs
from backend.forge.models import Agent, AgentMessage, MessageRole

_ORG_ID = "orgtest00000"


@pytest.fixture(autouse=True)
def test_db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    TS = sessionmaker(bind=eng)
    Base.metadata.create_all(eng)
    with patch("backend.services.SessionLocal", TS), \
         patch("backend.forge.services.SessionLocal", TS):
        db = TS()
        core_services._seed_defaults(db)
        db.add(Org(id=_ORG_ID, name="Test Org"))
        db.commit()
        db.close()
        yield TS


def _agent(name: str) -> str:
    # Insert the Agent row directly — list_all_conversations only needs the
    # agent + its messages, no runtime. org_id is set explicitly because the
    # auto-stamp before_flush hook is bound to the real SessionLocal, not the
    # test sessionmaker.
    with fs._session() as db:
        a = Agent(org_id=_ORG_ID, name=name, executor_type="cli")
        db.add(a)
        db.commit()
        return a.id


def _msg(agent_id: str, scope: str, content: str, minute: int):
    with fs._session() as db:
        db.add(AgentMessage(
            agent_id=agent_id, scope_key=scope, role=MessageRole.USER,
            content=content,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minute),
        ))
        db.commit()


def test_aggregates_across_agents_newest_first():
    a = _agent("Alpha")
    b = _agent("Beta")
    _msg(a, "chat:default", "hi from a", 1)
    _msg(b, "chat:default", "hi from b", 5)  # newest

    chats = fs.list_all_conversations()
    assert len(chats) == 2
    # Newest conversation first.
    assert chats[0]["agent_id"] == b
    assert chats[0]["agent_name"] == "Beta"
    assert chats[0]["last_message"] == "hi from b"
    assert chats[1]["agent_id"] == a


def test_separate_row_per_scope_with_counts():
    a = _agent("Alpha")
    _msg(a, "chat:default", "one", 1)
    _msg(a, "task:T1", "two", 2)
    _msg(a, "task:T1", "three", 3)

    chats = fs.list_all_conversations()
    by_scope = {c["scope_key"]: c for c in chats}
    assert by_scope["chat:default"]["message_count"] == 1
    assert by_scope["task:T1"]["message_count"] == 2
    assert by_scope["task:T1"]["last_message"] == "three"
