"""A2A inside Agentira: agents ask each other, visibly (backend/forge/a2a.py).

Delivery goes through forge_services.send_runtime_message (captured here);
the busy-target queue is the existing per-conversation msg_queue.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import backend.db as bdb
from backend import mcp_server, services as core_services
from backend.db import privileged
from backend.forge import a2a, msg_queue, services as forge_services
from backend.forge.models import (
    A2AMessage, A2AThread, ForgeRuntime, Run, RunStatus, RuntimeStatus,
)
from backend.models import Activity, Org, Task


@pytest.fixture(autouse=True)
def _db(pg):
    yield pg


@contextmanager
def _as(name: str):
    token = mcp_server.actor_ctx.set(name)
    try:
        yield
    finally:
        mcp_server.actor_ctx.reset(token)


def _call(tool, name: str, *args, **kw):
    with _as(name):
        return asyncio.run(tool(*args, **kw))


@pytest.fixture
def sent(monkeypatch):
    """Capture every send_runtime_message call: [(agent_id, kwargs)]."""
    calls: list[tuple[str, dict]] = []

    def fake(agent_id, **kw):
        calls.append((agent_id, kw))
        return {"ok": True}

    monkeypatch.setattr(forge_services, "send_runtime_message", fake)
    return calls


def _runtime() -> str:
    with bdb.SessionLocal() as db:
        rt = ForgeRuntime(daemon_id=uuid.uuid4().hex[:8], provider="claude",
                          binary_path="/tmp/c", status=RuntimeStatus.ONLINE)
        db.add(rt)
        db.commit()
        return rt.id


def _agent(name: str, rt_id: str | None = None) -> str:
    return forge_services.create_agent(
        name=name, executor_type="cli", model="sonnet",
        runtime_id=rt_id or _runtime())["id"]


@pytest.fixture
def world():
    """Project with two member agents (asker 'impl', target 'reviewer') and a task."""
    rt = _runtime()
    impl, rev = _agent("impl", rt), _agent("reviewer", rt)
    proj = core_services.create_project("P", actor="system")
    for n in ("impl", "reviewer"):
        core_services.add_project_member(proj["id"], n, actor="system")
    task = core_services.create_task(proj["id"], "Fix it", actor="system")
    return dict(impl=impl, rev=rev, project_id=proj["id"], task_id=task["id"], rt=rt)


def _run(agent_id: str, task_id: str | None, status=RunStatus.RUNNING) -> str:
    with forge_services._session() as db:
        r = Run(id=uuid.uuid4().hex[:12], agent_id=agent_id, task_id=task_id,
                status=status)
        db.add(r)
        db.commit()
        return r.id


# ── ask_agent ────────────────────────────────────────────────────────────

def test_ask_stores_thread_message_and_wakes_target(world, sent):
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "is the diff ok?")

    assert out["delivered"] is True and out["thread_id"] and out["message_id"]
    with bdb.SessionLocal() as db:
        th = db.get(A2AThread, out["thread_id"])
        msg = db.get(A2AMessage, out["message_id"])
        assert th.created_by_agent_id == world["impl"]
        assert (msg.from_agent_id, msg.to_agent_id, msg.kind) == (
            world["impl"], world["rev"], "ask")
        assert msg.body == "is the diff ok?"
    (agent_id, kw), = sent
    assert agent_id == world["rev"]
    assert kw["scope_key"] == f"a2a:{out['thread_id']}"
    # header: who asked, thread id, exactly how to answer
    assert "impl" in kw["content"] and out["thread_id"] in kw["content"]
    assert f'ask_agent(agent="impl", thread_id="{out["thread_id"]}"' in kw["content"]
    assert "is the diff ok?" in kw["content"]


def test_ask_with_task_mirrors_line_on_task_feed_and_names_task(world, sent):
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "look at this",
                task_id=world["task_id"])
    with bdb.SessionLocal() as db:
        th = db.get(A2AThread, out["thread_id"])
        assert th.task_id == world["task_id"] and th.project_id == world["project_id"]
        feed = [a.detail for a in db.query(Activity)
                .filter(Activity.task_id == world["task_id"]).all()]
    assert any("impl asked reviewer: look at this" in d for d in feed)
    assert "Fix it" in sent[0][1]["content"]


def test_ask_records_asker_live_run_as_origin(world, sent):
    run_id = _run(world["impl"], world["task_id"])
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "q")
    with bdb.SessionLocal() as db:
        th = db.get(A2AThread, out["thread_id"])
        assert th.origin_run_id == run_id
        assert th.origin_scope_key == f"task:{world['task_id']}"


def test_reply_routes_to_asker_wake_when_no_live_run(world, sent):
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "q")
    sent.clear()
    r = _call(mcp_server.ask_agent, "reviewer", "impl", "looks good",
              thread_id=out["thread_id"])
    assert r["thread_id"] == out["thread_id"]
    (agent_id, kw), = sent
    assert agent_id == world["impl"]
    assert kw["scope_key"] == f"a2a:{out['thread_id']}"
    assert "looks good" in kw["content"]
    with bdb.SessionLocal() as db:
        assert db.get(A2AMessage, r["message_id"]).kind == "reply"


def test_reply_lands_in_askers_live_run_conversation(world, sent):
    _run(world["impl"], world["task_id"])
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "q")
    sent.clear()
    _call(mcp_server.ask_agent, "reviewer", "impl", "answer", thread_id=out["thread_id"])
    (agent_id, kw), = sent
    assert agent_id == world["impl"]
    assert kw["scope_key"] == f"task:{world['task_id']}"
    assert "answer" in kw["content"]


def test_reply_after_asker_run_finished_wakes_a2a_scope(world, sent):
    run_id = _run(world["impl"], world["task_id"])
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "q")
    with forge_services._session() as db:
        db.get(Run, run_id).status = RunStatus.COMPLETED
        db.commit()
    sent.clear()
    _call(mcp_server.ask_agent, "reviewer", "impl", "answer", thread_id=out["thread_id"])
    assert sent[0][1]["scope_key"] == f"a2a:{out['thread_id']}"


def test_non_participant_cannot_post_to_thread(world, sent):
    _agent("third")
    core_services.add_project_member(world["project_id"], "third", actor="system")
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "q")
    r = _call(mcp_server.ask_agent, "third", "impl", "hi", thread_id=out["thread_id"])
    assert "error" in r


def test_self_message_rejected(world, sent):
    r = _call(mcp_server.ask_agent, "impl", "impl", "hello me")
    assert "yourself" in r["error"]
    assert not sent


def test_unknown_agent_rejected(world, sent):
    assert "error" in _call(mcp_server.ask_agent, "impl", "nobody", "hi")


def _agent_in_other_org(name: str) -> str:
    with privileged(), bdb.SessionLocal() as db:
        other = Org(name="Other")
        db.add(other)
        db.commit()
        other_id = other.id
    home = bdb.get_current_org()
    bdb.set_current_org(other_id)
    try:
        return _agent(name)
    finally:
        bdb.set_current_org(home)


def test_cross_org_rejected(world, sent):
    _agent_in_other_org("outsider")
    r = _call(mcp_server.ask_agent, "impl", "outsider", "psst")
    assert "error" in r and not sent


def test_archived_agent_rejected(world, sent):
    forge_services.delete_agent(world["rev"])
    r = _call(mcp_server.ask_agent, "impl", "reviewer", "hi")
    assert "error" in r and not sent


def test_rate_limit_30_per_thread_per_hour(world, sent):
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "m0")
    tid = out["thread_id"]
    for i in range(1, 30):
        assert "error" not in _call(mcp_server.ask_agent, "impl", "reviewer",
                                    f"m{i}", thread_id=tid)
    r = _call(mcp_server.ask_agent, "impl", "reviewer", "one too many", thread_id=tid)
    assert "error" in r and "30" in r["error"]


def test_rate_limit_ignores_messages_older_than_an_hour(world, sent):
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "m0")
    tid = out["thread_id"]
    for i in range(1, 30):
        _call(mcp_server.ask_agent, "impl", "reviewer", f"m{i}", thread_id=tid)
    with bdb.SessionLocal() as db:
        for m in db.query(A2AMessage).filter(A2AMessage.thread_id == tid).all():
            m.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        db.commit()
    assert "error" not in _call(mcp_server.ask_agent, "impl", "reviewer", "ok now",
                                thread_id=tid)


def test_body_capped(world, sent):
    r = _call(mcp_server.ask_agent, "impl", "reviewer", "x" * (a2a.MAX_BODY_CHARS + 1))
    assert "error" in r and not sent


def test_empty_body_rejected(world, sent):
    assert "error" in _call(mcp_server.ask_agent, "impl", "reviewer", "   ")


def test_not_an_agent_cannot_ask(world, sent):
    core_services.create_service_account("human-ish")
    assert "error" in _call(mcp_server.ask_agent, "human-ish", "reviewer", "hi")


def test_undeliverable_target_still_stores_message(world, monkeypatch):
    monkeypatch.setattr(forge_services, "send_runtime_message",
                        lambda *a, **k: {"success": False, "error": "no runtime"})
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "hi")
    assert out["delivered"] is False and out["message_id"]


# ── busy target: existing per-conversation queue holds it ────────────────

@patch("backend.forge.services._dispatch_coro", MagicMock(return_value=None))
def test_a2a_message_to_busy_agent_is_queued_then_flushed(world, monkeypatch):
    run_id = _run(world["rev"], world["task_id"])
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "when free?")
    scope = f"a2a:{out['thread_id']}"
    assert out["delivered"] is True
    queued = msg_queue.list_for_scope(agent_id=world["rev"], scope_key=scope)
    assert len(queued) == 1 and "when free?" in queued[0]["content"]

    flushed: list[tuple] = []
    monkeypatch.setattr(forge_services, "send_runtime_message",
                        lambda aid, **kw: flushed.append((aid, kw)) or {"ok": True})
    with forge_services._session() as db:
        db.get(Run, run_id).status = RunStatus.COMPLETED
        db.commit()
    assert msg_queue.flush_next(world["rev"], run_id=run_id) is True
    assert flushed[0][0] == world["rev"] and flushed[0][1]["scope_key"] == scope
    assert msg_queue.list_for_scope(agent_id=world["rev"], scope_key=scope) == []


# ── get_agent_thread ─────────────────────────────────────────────────────

def test_get_agent_thread_orders_messages(world, sent):
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "first")
    tid = out["thread_id"]
    _call(mcp_server.ask_agent, "reviewer", "impl", "second", thread_id=tid)
    _call(mcp_server.ask_agent, "impl", "reviewer", "third", thread_id=tid)
    t = _call(mcp_server.get_agent_thread, "impl", tid)
    assert [m["body"] for m in t["messages"]] == ["first", "second", "third"]
    assert [m["kind"] for m in t["messages"]] == ["ask", "reply", "ask"]
    assert t["messages"][0]["from"] == "impl" and t["messages"][0]["to"] == "reviewer"


def test_get_agent_thread_unknown_or_foreign(world, sent):
    out = _call(mcp_server.ask_agent, "impl", "reviewer", "first")
    _agent("third")
    assert "error" in _call(mcp_server.get_agent_thread, "third", out["thread_id"])
    assert "error" in _call(mcp_server.get_agent_thread, "impl", "nope")


# ── hand_off_task ────────────────────────────────────────────────────────

def test_hand_off_reassigns_comments_and_dispatches(world, monkeypatch):
    calls = []
    monkeypatch.setattr(
        forge_services, "schedule_task_run",
        lambda **kw: calls.append(kw) or {"run_id": "run123456789", "id": "run123456789"})
    out = _call(mcp_server.hand_off_task, "impl", world["task_id"], "reviewer",
                "please review the diff")
    assert out["run_id"] == "run123456789"
    assert calls and calls[0]["task_id"] == world["task_id"]
    assert calls[0]["agent_id"] == world["rev"]
    with bdb.SessionLocal() as db:
        assert db.get(Task, world["task_id"]).assignee == "reviewer"
        feed = [a.detail for a in db.query(Activity)
                .filter(Activity.task_id == world["task_id"]).all()]
    assert any("please review the diff" in d for d in feed)


def test_hand_off_to_self_rejected(world, monkeypatch):
    monkeypatch.setattr(forge_services, "schedule_task_run",
                        lambda **kw: pytest.fail("must not dispatch"))
    assert "error" in _call(mcp_server.hand_off_task, "impl", world["task_id"], "impl", "x")


def test_hand_off_dispatch_error_reported(world, monkeypatch):
    monkeypatch.setattr(forge_services, "schedule_task_run",
                        lambda **kw: {"error": "agent busy"})
    r = _call(mcp_server.hand_off_task, "impl", world["task_id"], "reviewer", "x")
    assert "agent busy" in r["error"]


def test_hand_off_needs_project_access(world, monkeypatch):
    monkeypatch.setattr(forge_services, "schedule_task_run",
                        lambda **kw: pytest.fail("must not dispatch"))
    _agent("outsider-in-org")
    r = _call(mcp_server.hand_off_task, "outsider-in-org", world["task_id"],
              "reviewer", "x")
    assert "error" in r


# ── list_agents ──────────────────────────────────────────────────────────

def test_list_agents_returns_cards_for_callers_org_only(world):
    with bdb.SessionLocal() as db:
        from backend.models import Profile
        p = db.query(Profile).filter(Profile.name == "reviewer").first()
        p.system_prompt = "You review pull requests.\nBe strict."
        db.commit()
    _run(world["rev"], world["task_id"])
    _agent_in_other_org("outsider")

    cards = _call(mcp_server.list_agents, "impl")
    names = {c["name"] for c in cards}
    assert names == {"impl", "reviewer"}
    rev = next(c for c in cards if c["name"] == "reviewer")
    assert rev["description"].startswith("You review pull requests")
    assert rev["runtime"] == "claude" and rev["model"] == "sonnet"
    assert rev["busy"] is True and "online" in rev
    assert world["project_id"] in [p["id"] for p in rev["projects"]]


def test_list_agents_filters_by_project(world):
    other_proj = core_services.create_project("Q", actor="system")
    _agent("solo")
    core_services.add_project_member(other_proj["id"], "solo", actor="system")
    names = {c["name"] for c in _call(mcp_server.list_agents, "impl",
                                      project_id=world["project_id"])}
    assert names == {"impl", "reviewer"}


def test_list_agents_hides_archived(world):
    forge_services.delete_agent(world["rev"])
    assert {c["name"] for c in _call(mcp_server.list_agents, "impl")} == {"impl"}
