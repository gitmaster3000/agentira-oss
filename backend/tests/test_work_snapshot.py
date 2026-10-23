"""Night snapshot — a token-free report of recent work and blockers."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import conductor as _conductor
from backend.forge import services as forge_services
from backend.forge import snapshot as snap
from backend.forge.models import (Agent, AgentMessage, ForgeRuntime, Run,
                                  RunOutcome, RunStatus, RuntimeStatus)
from backend.forge.scheduler import ForgeScheduler
from backend.models import Notification, Profile, Role, Task

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


@pytest.fixture(autouse=True)
def _db(pg):
    yield pg


def _admin() -> str:
    with bdb.SessionLocal() as db:
        role = db.query(Role).filter(Role.name == "admin").first()
        p = Profile(name="boss", account_type="human", roles=[role], password_hash="")
        db.add(p)
        db.commit()
        return p.id


def _runtime(*, heartbeat_ago_min: float | None, with_agent=True) -> str:
    with bdb.SessionLocal() as db:
        rt = ForgeRuntime(
            daemon_id=uuid.uuid4().hex[:8], provider="claude", binary_path="/c",
            status=RuntimeStatus.ONLINE,
            last_heartbeat=(NOW() - timedelta(minutes=heartbeat_ago_min)
                            if heartbeat_ago_min is not None else None))
        db.add(rt)
        db.commit()
        rt_id = rt.id
        if with_agent:
            bot = core_services.create_service_account("w-" + rt_id)
            db.add(Agent(id=bot["id"], profile_id=bot["id"], name="w-" + rt_id,
                         executor_type="http", model="", runtime_id=rt_id))
            db.commit()
        return rt_id


def _world():
    proj = core_services.create_project("Acme", actor="system")
    bot = core_services.create_service_account("worker")
    with bdb.SessionLocal() as db:
        db.add(Agent(id=bot["id"], profile_id=bot["id"], name="worker",
                     executor_type="http", model=""))
        db.commit()
    return proj["id"], bot["id"]


def _task(project_id, title, status="todo", *, ago_h=1.0) -> str:
    t = core_services.create_task(project_id, title, actor="system", status=status)
    with bdb.SessionLocal() as db:
        row = db.get(Task, t["id"])
        stamp = NOW() - timedelta(hours=ago_h)
        row.updated_at = stamp
        row.completed_at = stamp if status == "done" else None
        db.commit()
        return row.key


def _task_id(key):
    with bdb.SessionLocal() as db:
        return db.query(Task).filter(Task.key == key).first().id


def _run(agent_id, key, outcome, *, ago_h=1.0, summary="", status=None):
    st = status or (RunStatus.COMPLETED if outcome else RunStatus.RUNNING)
    stamp = NOW() - timedelta(hours=ago_h)
    with bdb.SessionLocal() as db:
        db.add(Run(agent_id=agent_id, task_id=_task_id(key), status=st,
                   outcome=outcome, summary=summary, created_at=stamp,
                   finished_at=stamp if outcome else None))
        db.commit()


def _project(s, name="Acme"):
    return next(p for p in s["projects"] if p["name"] == name)


# ── content ───────────────────────────────────────────────────────────

def test_lists_done_review_and_runs_and_ignores_older():
    pid, agent = _world()
    k_done = _task(pid, "Ship login", "done", ago_h=2)
    k_old = _task(pid, "Ancient win", "done", ago_h=30)
    k_rev = _task(pid, "Fix cart", "review", ago_h=3)
    _run(agent, k_done, RunOutcome.SUCCEEDED, ago_h=2, summary="Login shipped")
    _run(agent, k_old, RunOutcome.SUCCEEDED, ago_h=30, summary="old run")
    _run(agent, k_rev, RunOutcome.FAILED, ago_h=4, summary="tests red")

    s = snap.build_work_snapshot(since_hours=8)
    p = _project(s)
    assert [t["key"] for t in p["done"]] == [k_done]
    assert [t["key"] for t in p["to_review"]] == [k_rev]
    assert p["runs"]["succeeded"][0]["summary"] == "Login shipped"
    assert len(p["runs"]["succeeded"]) == 1
    assert p["runs"]["failed"][0]["summary"] == "tests red"
    assert k_old not in s["markdown"]
    assert set(s["window"]) >= {"since", "until", "hours"}


def test_project_filter():
    pid, agent = _world()
    _task(pid, "A", "done")
    other = core_services.create_project("Other", actor="system")
    s = snap.build_work_snapshot(since_hours=8, project_id=other["id"])
    assert [p["name"] for p in s["projects"]] == ["Other"]


def test_in_flight_listed():
    pid, agent = _world()
    k = _task(pid, "Long job", "in_progress")
    _run(agent, k, None, status=RunStatus.RUNNING)
    p = _project(snap.build_work_snapshot())
    assert [t["key"] for t in p["in_flight"]] == [k]


# ── blockers ──────────────────────────────────────────────────────────

def test_blockers_needs_input_and_answered_not_listed():
    pid, agent = _world()
    k = _task(pid, "Which db?", "in_progress")
    _run(agent, k, RunOutcome.NEEDS_INPUT, ago_h=2, summary="Postgres or MySQL?")
    k2 = _task(pid, "Answered", "in_progress")
    _run(agent, k2, RunOutcome.NEEDS_INPUT, ago_h=3, summary="old question")
    _run(agent, k2, RunOutcome.SUCCEEDED, ago_h=1, summary="resolved")
    s = snap.build_work_snapshot()
    blockers = _project(s)["blockers"]
    assert [b["key"] for b in blockers] == [k]
    assert blockers[0]["kind"] == "needs_input"
    assert "Postgres or MySQL?" in blockers[0]["text"]


def test_blocker_when_redispatch_attempts_spent():
    pid, agent = _world()
    k = _task(pid, "Flaky", "todo")
    for h in (5, 4, 3):
        _run(agent, k, RunOutcome.FAILED, ago_h=h, status=RunStatus.FAILED)
    kinds = [b["kind"] for b in _project(snap.build_work_snapshot())["blockers"]]
    assert "retries_spent" in kinds


def test_offline_runtime_is_a_blocker_with_plain_message():
    _world()
    _runtime(heartbeat_ago_min=30)
    _runtime(heartbeat_ago_min=1)
    s = snap.build_work_snapshot()
    assert len(s["health"]["runtimes_offline"]) == 1
    assert s["health"]["daemon_last_heartbeat"]
    assert "Agents are offline: the daemon has not checked in since" in s["markdown"]


def test_unbound_stale_runtime_ignored():
    _world()
    _runtime(heartbeat_ago_min=600, with_agent=False)
    assert snap.build_work_snapshot()["health"]["runtimes_offline"] == []


def test_markdown_links_tasks():
    pid, agent = _world()
    k = _task(pid, "Ship", "done")
    md = snap.build_work_snapshot()["markdown"]
    assert f"[{k}](/studio/tasks/{k})" in md


def test_allowed_project_ids_limits_scope_and_hides_health():
    pid, _ = _world()
    core_services.create_project("Secret", actor="system")
    _runtime(heartbeat_ago_min=30)
    s = snap.build_work_snapshot(allowed_project_ids=[pid])
    assert [p["name"] for p in s["projects"]] == ["Acme"]
    assert s["health"]["runtimes_offline"] == []


# ── schedule + posting ────────────────────────────────────────────────

def _conductor_with_interval(hours):
    cond = _conductor.get_or_create_conductor()
    forge_services.update_agent(cond["id"], conductor_snapshot_interval_hours=hours)
    return cond["id"]


def test_config_exposes_interval_default_zero():
    _conductor.get_or_create_conductor()
    assert _conductor.get_conductor_config()["snapshot_interval_hours"] == 0


def test_agent_dict_and_status_endpoint_expose_interval():
    cid = _conductor_with_interval(6)
    assert forge_services.get_agent(cid)["conductor_snapshot_interval_hours"] == 6
    from fastapi.testclient import TestClient
    from backend.rest_api import app
    from backend.jwt_auth import create_token
    admin_id = _admin()
    tok = create_token("boss", admin_id, ["admin"], org_id=bdb.get_current_org())
    c = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    body = c.get("/api/forge/conductor").json()
    assert body["config"]["snapshot_interval_hours"] == 6
    assert "last_snapshot" in body


def test_interval_zero_schedules_nothing():
    _conductor_with_interval(0)
    sched = ForgeScheduler()
    sched._scheduler.start(paused=True)
    sched._reschedule_conductor()
    assert sched._scheduler.get_job("conductor_snapshot") is None
    sched._scheduler.shutdown(wait=False)


def test_interval_n_schedules_job():
    _conductor_with_interval(4)
    sched = ForgeScheduler()
    sched._scheduler.start(paused=True)
    sched._reschedule_conductor()
    job = sched._scheduler.get_job("conductor_snapshot")
    assert job is not None
    assert job.trigger.interval == timedelta(hours=4)
    sched._scheduler.shutdown(wait=False)


def _notes():
    with bdb.SessionLocal() as db:
        return db.query(Notification).filter(
            Notification.type == "conductor.snapshot").all()


def test_quiet_window_posts_nothing():
    _conductor_with_interval(4)
    _admin()
    _world()
    r = snap.run_snapshot_job()
    assert r["posted"] is False
    assert _notes() == []


def test_blocker_posts_one_notification_per_admin_and_chat_message():
    cid = _conductor_with_interval(4)
    _admin()
    pid, agent = _world()
    k = _task(pid, "Which db?", "in_progress")
    _run(agent, k, RunOutcome.NEEDS_INPUT, summary="Postgres or MySQL?")
    r = snap.run_snapshot_job()
    assert r["posted"] is True
    notes = _notes()
    assert len(notes) == 1
    assert notes[0].link
    with bdb.SessionLocal() as db:
        msgs = db.query(AgentMessage).filter(AgentMessage.agent_id == cid).all()
    assert len(msgs) == 1 and k in msgs[0].content
    assert _conductor.get_last_snapshot()["posted"] is True
    # token-free: nothing went to a runtime
    assert msgs[0].input_tokens == 0 and msgs[0].output_tokens == 0


def test_activity_without_blocker_posts():
    _conductor_with_interval(4)
    _admin()
    pid, agent = _world()
    k = _task(pid, "Ship", "done")
    _run(agent, k, RunOutcome.SUCCEEDED)
    assert snap.run_snapshot_job()["posted"] is True


def test_job_noop_when_interval_zero():
    _conductor_with_interval(0)
    _admin()
    assert snap.run_snapshot_job() == {"skipped": "snapshot_off"}


# ── MCP ───────────────────────────────────────────────────────────────

def test_mcp_tool_returns_markdown_and_dict():
    import asyncio
    from backend import mcp_server
    pid, agent = _world()
    _task(pid, "Ship", "done")
    tok = mcp_server.actor_ctx.set("system")
    try:
        out = asyncio.run(mcp_server.get_work_snapshot(since_hours=8))
    finally:
        mcp_server.actor_ctx.reset(tok)
    assert "markdown" in out and "projects" in out["snapshot"]
