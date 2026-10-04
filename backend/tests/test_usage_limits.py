"""Usage limits pause runs and resume them at reset (classify + pause + resume)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import usage_limits as limits
from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime, Run, RunStatus, RuntimeStatus

NOW = datetime(2026, 9, 30, 3, 0, tzinfo=timezone.utc)  # 05:00 in Berlin (CEST)
CLAUDE_MSG = "You've hit your session limit · resets 6:20am (Europe/Berlin)"
CODEX_MSG = "You've hit your usage limit. Upgrade to Pro or try again in 2 hours 5 minutes."


# ── classify ─────────────────────────────────────────────────────────

def test_claude_reset_time_parsed_in_its_timezone():
    hit = limits.classify(CLAUDE_MSG, NOW)
    assert hit.reset_at == datetime(2026, 9, 30, 4, 20, tzinfo=timezone.utc)


def test_claude_reset_already_passed_today_means_tomorrow():
    later = datetime(2026, 9, 30, 5, 0, tzinfo=timezone.utc)  # 07:00 Berlin
    assert limits.classify(CLAUDE_MSG, later).reset_at.day == 1  # Oct 1


def test_claude_epoch_form():
    hit = limits.classify("Claude AI usage limit reached|1790000000", NOW)
    assert hit.reset_at == datetime.fromtimestamp(1790000000, timezone.utc)


def test_codex_relative_time():
    hit = limits.classify(CODEX_MSG, NOW)
    assert hit.reset_at == NOW + timedelta(hours=2, minutes=5)


def test_limit_without_reset_time():
    hit = limits.classify("You've hit your usage limit", NOW)
    assert hit is not None and hit.reset_at is None


@pytest.mark.parametrize("msg", ["", None, "subprocess exited with code 1",
                                 "rate limit of tokens per minute exceeded?"])
def test_non_limit_errors_are_not_classified(msg):
    assert limits.classify(msg, NOW) is None


def test_backoff_without_reset_is_30min_then_hourly():
    pol = limits.policy()
    hit = limits.classify("You've hit your usage limit", NOW)
    assert limits.resume_time(hit, 0, NOW, pol) == NOW + timedelta(minutes=30)
    assert limits.resume_time(hit, 1, NOW, pol) == NOW + timedelta(hours=1)


def test_backoff_policy_comes_from_config(monkeypatch):
    monkeypatch.setenv("FORGE_LIMIT_FIRST_BACKOFF_S", "60")
    hit = limits.classify("You've hit your usage limit", NOW)
    assert limits.resume_time(hit, 0, NOW, limits.policy()) == NOW + timedelta(seconds=60)


def test_rest_label_plain_words():
    assert limits.rest_label(datetime(2026, 9, 30, 6, 20, tzinfo=timezone.utc)) \
        == "Resting until 06:20 UTC — usage limit"


# ── pause / gate / resume (Postgres) ─────────────────────────────────

@pytest.fixture
def world(pg):
    with bdb.SessionLocal() as db:
        rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                          status=RuntimeStatus.ONLINE, last_heartbeat=NOW)
        db.add(rt)
        db.commit()
        rt_id = rt.id
    project = core_services.create_project("P", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli", runtime_id=rt_id)
    run = forge_services.create_run(agent_id=agent["id"], project_id=project["id"])
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == run["id"]).first()
        r.status = RunStatus.RUNNING
        db.commit()
    return {"run_id": run["id"], "agent_id": agent["id"], "runtime_id": rt_id}


def _run(run_id):
    with bdb.SessionLocal() as db:
        return db.query(Run).filter(Run.id == run_id).first()


def _complete(w, error, session_id="sess-1"):
    return forge_services.complete_trigger(
        w["agent_id"], trace_id="t1", run_id=w["run_id"], success=False,
        error=error, session_id=session_id)


def test_limit_error_pauses_run_instead_of_failing(world):
    res = _complete(world, "You've hit your usage limit")
    r = _run(world["run_id"])
    assert res["paused"] is True
    assert r.status == RunStatus.PAUSED and r.pause_reason == "usage_limit"
    assert r.resume_at is not None and r.error is None
    assert r.session_id == "sess-1" and r.limit_hits == 1


def test_ordinary_error_still_fails(world):
    _complete(world, "boom")
    assert _run(world["run_id"]).status == RunStatus.FAILED


def test_pause_budget_spent_fails_the_run(world, monkeypatch):
    monkeypatch.setenv("FORGE_LIMIT_MAX_PAUSES", "0")
    _complete(world, "You've hit your usage limit")
    assert _run(world["run_id"]).status == RunStatus.FAILED


def test_runtime_limited_blocks_new_dispatch_and_shows_in_agent(world):
    _complete(world, "You've hit your usage limit")
    res = forge_services.dispatch_trigger(world["agent_id"], "hi")
    assert "Resting until" in res["error"] and res["resting_until"]
    agent = forge_services.get_agent(world["agent_id"])
    assert agent["rest_label"].startswith("Resting until")
    with bdb.SessionLocal() as db:
        run_dict = forge_services._run_to_dict(
            db.query(Run).filter(Run.id == world["run_id"]).first())
    assert run_dict["rest_label"].startswith("Resting until")


def test_resume_waits_for_reset_then_resumes_same_run(world):
    _complete(world, "You've hit your usage limit")
    r = _run(world["run_id"])
    resume_at = r.resume_at if r.resume_at.tzinfo else r.resume_at.replace(tzinfo=timezone.utc)
    calls = []

    def fake_dispatch(*, run_id, resume, model_override="", **_):
        calls.append((run_id, resume, model_override))
        return {"ok": True}

    with patch.object(forge_services, "dispatch_pending_run", fake_dispatch):
        assert limits.resume_due_runs(now=resume_at - timedelta(seconds=5)) == []
        assert calls == []
        # The runtime limit clears at resume_at, so the sweep relaunches the run.
        assert limits.resume_due_runs(now=resume_at + timedelta(seconds=1)) == [world["run_id"]]
    assert calls == [(world["run_id"], True, "")]
    r = _run(world["run_id"])
    assert r.status == RunStatus.PENDING and r.pause_reason is None and r.resume_at is None
    assert limits.runtime_limit(world["runtime_id"],
                                now=resume_at + timedelta(seconds=1)) is None


def test_fallback_model_resumes_immediately_on_that_model(world):
    with forge_services._session() as db:
        from backend.forge.models import Agent
        db.query(Agent).filter(Agent.id == world["agent_id"]).update(
            {"config_json": '{"fallback_model": "gpt-5-codex"}'})
        db.commit()
    _complete(world, "You've hit your usage limit")
    calls = []
    with patch.object(forge_services, "dispatch_pending_run",
                      lambda **kw: calls.append(kw) or {"ok": True}):
        assert limits.resume_due_runs() == [world["run_id"]]
    assert calls[0]["model_override"] == "gpt-5-codex"
