"""get_run_events / get_trigger_events must be bounded.

Regression (AP-391 root cause): /runs/{id}/events returned a run's ENTIRE
message history with uncapped content/tool_input/tool_output. RunDetail polls
it every 5s; on a long sticky run each poll materialized gigabytes and the
prod container OOM-killed (stair-step RSS growth to ~8GB, then `Killed`).
The loaders must return only the newest window, ascending within it, with
per-field trims.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as fs
from backend.forge.models import (
    AgentMessage, MessageRole, ForgeRuntime, RuntimeStatus, Run, RunStatus,
)


@pytest.fixture(autouse=True)
def test_db(pg):
    yield bdb.SessionLocal


def _seed_run_with_messages(n: int, *, content_fn=None) -> str:
    with fs._session() as db:
        rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/c",
                          status=RuntimeStatus.ONLINE)
        db.add(rt); db.commit(); rt_id = rt.id
    agent = fs.create_agent(name="A", executor_type="cli", runtime_id=rt_id)
    proj = core_services.create_project("P")
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with fs._session() as db:
        run = Run(agent_id=agent["id"], project_id=proj["id"],
                  status=RunStatus.RUNNING)
        db.add(run); db.commit(); run_id = run.id
        for i in range(n):
            db.add(AgentMessage(
                agent_id=agent["id"], run_id=run_id, trace_id="tr1",
                role=MessageRole.USER,
                content=(content_fn(i) if content_fn else f"msg {i}"),
                created_at=base + timedelta(seconds=i),
            ))
        db.commit()
    return run_id


def test_run_events_returns_newest_window_ascending(monkeypatch):
    monkeypatch.setattr(fs, "_RUN_EVENTS_WINDOW", 5)
    run_id = _seed_run_with_messages(8)
    events = fs.get_run_events(run_id)
    assert len(events) == 5
    # Newest 5 (msg 3..7), ascending for display.
    assert events[0]["content"] == "msg 3"
    assert events[-1]["content"] == "msg 7"


def test_run_events_trims_large_fields(monkeypatch):
    monkeypatch.setattr(fs, "_RUN_EVENT_FIELD_CAP", 10)
    run_id = _seed_run_with_messages(1, content_fn=lambda i: "x" * 1000)
    events = fs.get_run_events(run_id)
    assert len(events) == 1
    assert events[0]["content"] == "x" * 10 + "…[truncated]"


def test_trigger_events_windowed(monkeypatch):
    monkeypatch.setattr(fs, "_RUN_EVENTS_WINDOW", 5)
    _seed_run_with_messages(8)
    events = fs.get_trigger_events("tr1")
    assert len(events) == 5
    assert events[0]["content"] == "msg 3"
    assert events[-1]["content"] == "msg 7"
