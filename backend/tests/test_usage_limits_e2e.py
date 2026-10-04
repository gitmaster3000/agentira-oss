"""End to end: a fake runtime hits a usage limit, the run pauses, then resumes by itself.

The "runtime" is a fake daemon on the hub seam: it receives the dispatch frame
and answers with trigger-complete exactly as the real daemon would. Everything
else — dispatch, complete_trigger, pause, runtime gate, scheduler sweep, resume —
is the real code on Postgres.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge import usage_limits as limits
from backend.forge.models import ForgeRuntime, Run, RunStatus, RuntimeStatus

LIMIT_MSG = "You've hit your session limit · resets 6:20am (Europe/Berlin)"


def test_run_pauses_on_limit_and_resumes_by_itself(pg, monkeypatch, capsys):
    sent: list[dict] = []        # frames the fake daemon received
    script = [LIMIT_MSG, None]   # turn 1 hits the limit, turn 2 succeeds

    def fake_dispatch_trigger(**frame):
        sent.append(frame)
        return object()

    monkeypatch.setattr("backend.forge.ws_dispatch.hub.dispatch_trigger", fake_dispatch_trigger)
    monkeypatch.setattr(forge_services, "_dispatch_coro", lambda coro: coro)

    def fake_runtime_finishes_turn(agent_id, run_id):
        err = script.pop(0)
        return forge_services.complete_trigger(
            agent_id, trace_id=sent[-1].get("trace_id", "t"), run_id=run_id,
            success=err is None, error=err or "", session_id="claude-session-42")

    def show(step):
        with bdb.SessionLocal() as db:
            r = db.query(Run).filter(Run.id == run_id).first()
            rt = db.get(ForgeRuntime, rt_id)
            line = (f"{step:<34} run={r.status.value:<9} reason={r.pause_reason} "
                    f"resume_at={r.resume_at and r.resume_at.isoformat()} "
                    f"runtime_limited_until={rt.limited_until and rt.limited_until.isoformat()}")
        with capsys.disabled():
            print(line)

    with bdb.SessionLocal() as db:
        rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                          status=RuntimeStatus.ONLINE,
                          last_heartbeat=datetime.now(timezone.utc),
                          capabilities='["resume"]')
        db.add(rt)
        db.commit()
        rt_id = rt.id
    project = core_services.create_project("P", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli", runtime_id=rt_id)
    run_id = forge_services.create_run(agent_id=agent["id"], project_id=project["id"])["id"]
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run_id).first()
        r.initial_prompt = "do the work"
        r.status = RunStatus.PENDING
        db.commit()

    forge_services.dispatch_pending_run(run_id=run_id)
    show("1. dispatched to fake runtime")
    assert sent

    res = fake_runtime_finishes_turn(agent["id"], run_id)
    show("2. runtime reports limit error")
    assert res["paused"] and _status(run_id) == RunStatus.PAUSED

    blocked = forge_services.dispatch_trigger(agent["id"], "new work")
    with capsys.disabled():
        print(f"3. new dispatch to resting runtime -> {blocked['error']!r}")
    assert blocked["error"].startswith("Resting until")

    with bdb.SessionLocal() as db:
        resume_at = db.query(Run).filter(Run.id == run_id).first().resume_at
    resume_at = resume_at.replace(tzinfo=timezone.utc) if resume_at.tzinfo is None else resume_at
    assert limits.resume_due_runs(now=resume_at - timedelta(minutes=1)) == []
    show("4. sweep one minute before reset")
    assert _status(run_id) == RunStatus.PAUSED

    n_frames = len(sent)
    after_reset = resume_at + timedelta(seconds=1)
    monkeypatch.setattr(limits, "_now", lambda: after_reset)  # advance the clock
    assert limits.resume_due_runs() == [run_id]
    show("5. sweep after reset -> resumed")
    assert len(sent) == n_frames + 1

    fake_runtime_finishes_turn(agent["id"], run_id)
    show("6. runtime finishes the turn")
    assert _status(run_id) == RunStatus.COMPLETED
    with capsys.disabled():
        print(f"resume frame session handle: {sent[-1].get('resume_session_id')!r}")


def _status(run_id):
    with bdb.SessionLocal() as db:
        return db.query(Run).filter(Run.id == run_id).first().status
