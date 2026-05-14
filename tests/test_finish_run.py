"""Tests for AP-53 — finish_run + RunOutcome semantic state.

Covers the service layer contract (validation, idempotency, summary
storage, default-on-completion behavior) and the prompt template's
finish_run instruction surface. The MCP tool wrapper is a thin shim
over the service so we don't separately test the @mcp.tool() decorator.
"""

import asyncio
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    Run, RunStatus, RunOutcome, ForgeRuntime, RuntimeStatus,
)


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _make_run(test_db) -> str:
    """Create an agent + task + run; return run_id."""
    db = test_db()
    rt = ForgeRuntime(daemon_id="d", provider="claude",
                       binary_path="/tmp/c", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()

    project = core_services.create_project("FR Project", actor="system")
    task = core_services.create_task(project["id"], "FR Task", actor="system")
    agent = forge_services.create_agent(name="FR Agent", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(
        agent_id=agent["id"], task_id=task["id"], project_id=project["id"],
    )
    return run["id"]


# ── Run serializer ─────────────────────────────────────────────────────

def test_run_serializer_includes_outcome_and_summary(test_db):
    rid = _make_run(test_db)
    run = forge_services.get_run(rid)
    assert "outcome" in run
    assert "summary" in run
    assert run["outcome"] is None
    assert run["summary"] == ""


# ── finish_run validation ──────────────────────────────────────────────

def test_finish_run_rejects_unknown_outcome(test_db):
    rid = _make_run(test_db)
    res = forge_services.finish_run(rid, outcome="success",  # singular typo
                                     summary="ignored")
    assert res["ok"] is False
    assert "succeeded" in res["error"]  # message lists valid options


def test_finish_run_rejects_missing_run(test_db):
    res = forge_services.finish_run("ghost_run_xyz", outcome="succeeded",
                                     summary="x")
    assert res["ok"] is False
    assert "not found" in res["error"].lower()


# ── finish_run happy paths ────────────────────────────────────────────

def test_finish_run_sets_outcome_and_summary(test_db):
    rid = _make_run(test_db)
    res = forge_services.finish_run(
        rid, outcome="succeeded",
        summary="Wrote the README and ran tests.",
    )
    assert res["ok"] is True
    assert res["run"]["outcome"] == "succeeded"
    assert res["run"]["summary"] == "Wrote the README and ran tests."

    # Persisted, not just echoed.
    fetched = forge_services.get_run(rid)
    assert fetched["outcome"] == "succeeded"
    assert fetched["summary"] == "Wrote the README and ran tests."


def test_finish_run_blocked_with_reason(test_db):
    rid = _make_run(test_db)
    res = forge_services.finish_run(
        rid, outcome="blocked",
        summary="Need DATABASE_URL — staging credentials missing.",
    )
    assert res["ok"] is True
    assert res["run"]["outcome"] == "blocked"


def test_finish_run_needs_input(test_db):
    rid = _make_run(test_db)
    res = forge_services.finish_run(rid, outcome="needs_input",
                                     summary="Two valid approaches; please pick.")
    assert res["ok"] is True
    assert res["run"]["outcome"] == "needs_input"


def test_finish_run_is_idempotent_for_same_outcome(test_db):
    rid = _make_run(test_db)
    forge_services.finish_run(rid, outcome="succeeded", summary="v1")
    res = forge_services.finish_run(rid, outcome="succeeded", summary="v1")
    assert res["ok"] is True
    assert res["run"]["outcome"] == "succeeded"


def test_finish_run_can_revise_outcome(test_db):
    """Agent realizes mid-stream they were wrong → updates verdict."""
    rid = _make_run(test_db)
    forge_services.finish_run(rid, outcome="succeeded", summary="initial")
    res = forge_services.finish_run(
        rid, outcome="blocked",
        summary="Actually I can't write the file — perms.",
    )
    assert res["run"]["outcome"] == "blocked"
    assert "perms" in res["run"]["summary"]


def test_finish_run_empty_summary_keeps_existing(test_db):
    rid = _make_run(test_db)
    forge_services.finish_run(rid, outcome="succeeded", summary="real summary")
    # Subsequent call with no summary doesn't blank it out.
    forge_services.finish_run(rid, outcome="succeeded", summary="")
    assert forge_services.get_run(rid)["summary"] == "real summary"


# ── complete_trigger default outcome ──────────────────────────────────

def test_complete_trigger_defaults_outcome_to_succeeded_when_unset(test_db):
    """Agent that didn't call finish_run gets a sensible default — better
    than leaving outcome=null forever."""
    rid = _make_run(test_db)
    forge_services.complete_trigger(
        agent_id="any", trace_id="t", run_id=rid,
        success=True, input_tokens=10, output_tokens=20, error=None,
    )
    assert forge_services.get_run(rid)["outcome"] == "succeeded"


def test_complete_trigger_defaults_to_failed_when_process_died(test_db):
    rid = _make_run(test_db)
    forge_services.complete_trigger(
        agent_id="any", trace_id="t", run_id=rid,
        success=False, error="boom",
    )
    assert forge_services.get_run(rid)["outcome"] == "failed"


def test_complete_trigger_persists_diff_and_diff_stat(test_db):
    rid = _make_run(test_db)
    forge_services.complete_trigger(
        agent_id="any", trace_id="t", run_id=rid,
        success=True, error=None,
        diff_stat=" README.md | 2 ++\n 1 file changed",
        diff="--- a/README.md\n+++ b/README.md\n@@ +new line",
    )
    run = forge_services.get_run(rid)
    assert "README.md" in run["diff_stat"]
    assert "+new line" in run["diff"]


def test_complete_trigger_empty_diff_does_not_overwrite(test_db):
    rid = _make_run(test_db)
    # Pre-seed a diff via the same path (a hypothetical earlier completion).
    forge_services.complete_trigger(
        agent_id="any", trace_id="t1", run_id=rid,
        success=True, diff_stat="stat-1", diff="diff-1",
    )
    # Second call without diff payload — must not blank existing values.
    forge_services.complete_trigger(
        agent_id="any", trace_id="t2", run_id=rid,
        success=True,
    )
    run = forge_services.get_run(rid)
    assert run["diff_stat"] == "stat-1"
    assert run["diff"] == "diff-1"


def test_complete_trigger_does_not_clobber_agent_set_outcome(test_db):
    """If finish_run already set outcome=blocked, complete_trigger must
    NOT downgrade it to succeeded just because the process exited 0."""
    rid = _make_run(test_db)
    forge_services.finish_run(rid, outcome="blocked",
                               summary="missing creds")
    forge_services.complete_trigger(
        agent_id="any", trace_id="t", run_id=rid,
        success=True, error=None,
    )
    # Agent's verdict wins.
    assert forge_services.get_run(rid)["outcome"] == "blocked"
    assert forge_services.get_run(rid)["summary"] == "missing creds"


# ── Prompt template ──────────────────────────────────────────────────

class _FakeHub:
    def __init__(self):
        self.calls: list[dict] = []

    async def dispatch_trigger(self, **kwargs):
        self.calls.append(kwargs)


def _drive(fn):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = fn()
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        return result
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_schedule_task_run_prompt_includes_finish_run_instruction(test_db):
    db = test_db()
    rt = ForgeRuntime(daemon_id="d", provider="claude",
                       binary_path="/tmp/c", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()

    project = core_services.create_project("Tmpl Project", actor="system")
    task = core_services.create_task(project["id"], "Tmpl Task", actor="system")
    agent = forge_services.create_agent(name="Tmpl Agent", executor_type="cli",
                                        runtime_id=rt_id)

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        result = _drive(lambda: forge_services.schedule_task_run(
            task_id=task["id"], agent_id=agent["id"],
        ))

    prompt = fake.calls[0]["prompt"]
    assert "finish_run" in prompt
    assert "succeeded" in prompt
    assert "blocked" in prompt
    assert "needs_input" in prompt
    # The real run_id (not the placeholder) must be substituted in.
    assert "{run_id}" not in prompt
    assert result["run_id"] in prompt
