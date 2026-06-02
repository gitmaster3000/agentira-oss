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
    AgentMessage, MessageRole,
)


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.runs.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _make_run(test_db) -> str:
    """Create an agent + task + run; return run_id.

    Stamps a synthetic diff_stat on the run so the empty-success guard
    in finish_run lets `outcome=succeeded` through — these tests are
    about finish_run semantics, not about the deliverable requirement
    which has its own test file (test_empty_success_guard.py)."""
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
    with forge_services._session() as db:
        r = db.query(forge_services.Run).filter(forge_services.Run.id == run["id"]).first()
        r.diff_stat = " 1 file changed, 1 insertion(+)"
        db.commit()
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


# ── failure message must land in the chat scope ────────────────────────
# A failure system-message with scope_key=None never reaches the
# scope-filtered chat thread, so the "thinking…" spinner spins forever.

def test_failure_message_carries_scope_from_trace_map(test_db):
    """When the in-flight trace is still in _TRACE_SCOPE, the failure
    message inherits that scope."""
    forge_services._TRACE_SCOPE["tscope"] = "chat:default"
    try:
        forge_services.complete_trigger(
            agent_id="agentX", trace_id="tscope", run_id=None,
            success=False, error="boom",
        )
    finally:
        forge_services._TRACE_SCOPE.pop("tscope", None)
    db = test_db()
    msg = (db.query(AgentMessage)
             .filter(AgentMessage.trace_id == "tscope",
                     AgentMessage.role == MessageRole.SYSTEM)
             .first())
    db.close()
    assert msg is not None
    assert msg.scope_key == "chat:default"


def test_failure_message_recovers_scope_from_db_after_restart(test_db):
    """_TRACE_SCOPE is in-memory and empty after a backend restart. The
    failure message must still land in the right thread by recovering the
    scope from the user prompt already persisted under this trace."""
    db = test_db()
    db.add(AgentMessage(
        agent_id="agentX", trace_id="trec", scope_key="task:abc123",
        role=MessageRole.USER, content="do the thing",
    ))
    db.commit()
    db.close()

    # _TRACE_SCOPE deliberately has no entry for this trace.
    assert "trec" not in forge_services._TRACE_SCOPE
    forge_services.complete_trigger(
        agent_id="agentX", trace_id="trec", run_id=None,
        success=False, error="subprocess exited with code 1",
    )

    db = test_db()
    msg = (db.query(AgentMessage)
             .filter(AgentMessage.trace_id == "trec",
                     AgentMessage.role == MessageRole.SYSTEM)
             .first())
    db.close()
    assert msg is not None
    assert msg.scope_key == "task:abc123"


def test_dispatch_dropped_message_carries_scope_from_trace_map(test_db):
    """A 'no daemon online' drop must surface in the chat scope — else the
    floating chat's thinking spinner spins forever."""
    forge_services._TRACE_SCOPE["tdrop"] = "chat:default"
    try:
        forge_services.mark_dispatch_dropped(
            agent_id="agentX", trace_id="tdrop", run_id=None)
    finally:
        forge_services._TRACE_SCOPE.pop("tdrop", None)
    db = test_db()
    msg = (db.query(AgentMessage)
             .filter(AgentMessage.trace_id == "tdrop",
                     AgentMessage.role == MessageRole.SYSTEM)
             .first())
    db.close()
    assert msg is not None
    assert msg.scope_key == "chat:default"
    assert "No daemon online" in msg.content


def test_dispatch_dropped_recovers_scope_from_db(test_db):
    """_TRACE_SCOPE empty (backend restart) — scope is recovered from the
    user prompt persisted under this trace."""
    db = test_db()
    db.add(AgentMessage(
        agent_id="agentX", trace_id="tdrop2", scope_key="chat:default",
        role=MessageRole.USER, content="test"))
    db.commit()
    db.close()
    assert "tdrop2" not in forge_services._TRACE_SCOPE
    forge_services.mark_dispatch_dropped(
        agent_id="agentX", trace_id="tdrop2", run_id=None)
    db = test_db()
    msg = (db.query(AgentMessage)
             .filter(AgentMessage.trace_id == "tdrop2",
                     AgentMessage.role == MessageRole.SYSTEM)
             .first())
    db.close()
    assert msg is not None
    assert msg.scope_key == "chat:default"


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


# ── AP-108: agent verdict outranks process exit code ───────────────────

def test_nonzero_exit_after_finish_run_does_not_fail_the_run(test_db):
    """The agent called finish_run(succeeded), then the subprocess exited
    non-zero (e.g. SIGTERM from a pause). The run must stay COMPLETED —
    the agent's verdict is authoritative — not flip to FAILED."""
    rid = _make_run(test_db)
    forge_services.finish_run(rid, outcome="succeeded",
                               summary="Implemented the service.")
    forge_services.complete_trigger(
        agent_id="any", trace_id="t", run_id=rid,
        success=False, error="subprocess exited with code 1",
    )
    run = forge_services.get_run(rid)
    assert run["status"] == "completed", run["status"]
    assert run["outcome"] == "succeeded"
    assert run["summary"] == "Implemented the service."
    # The misleading "execution failed" message must NOT be posted.
    db = test_db()
    sysmsgs = (db.query(AgentMessage)
               .filter(AgentMessage.run_id == rid,
                       AgentMessage.role == MessageRole.SYSTEM)
               .all())
    db.close()
    assert not any("execution failed" in m.content for m in sysmsgs)


def test_nonzero_exit_with_no_agent_outcome_still_fails(test_db):
    """No finish_run call → the process exit is the only signal we have,
    so a non-zero exit fails the run. (Auto-retry is stubbed — the
    crashed run itself still ends FAILED; the retry is a separate run.)"""
    rid = _make_run(test_db)
    with patch.object(forge_services, "schedule_task_run",
                      lambda **kw: {"ok": True, "run_id": "retry"}):
        forge_services.complete_trigger(
            agent_id="any", trace_id="t", run_id=rid,
            success=False, error="subprocess exited with code 1",
        )
    run = forge_services.get_run(rid)
    assert run["status"] == "failed"
    assert run["outcome"] == "failed"


# ── auto-retry on transient crash ──────────────────────────────────────

def test_transient_crash_auto_retries(test_db):
    """A bare 'subprocess exited with code 1' (no agent verdict) is a
    transient crash — complete_trigger re-dispatches the task."""
    rid = _make_run(test_db)
    calls = []

    def fake_sched(*, task_id, agent_id, **kw):
        calls.append((task_id, agent_id))
        return {"ok": True, "run_id": "retry-run"}

    with patch.object(forge_services, "schedule_task_run", fake_sched):
        res = forge_services.complete_trigger(
            agent_id="any", trace_id="t", run_id=rid,
            success=False, error="subprocess exited with code 1")
    assert res.get("auto_retried") is True
    assert len(calls) == 1


def test_user_cancel_does_not_auto_retry(test_db):
    """A user cancel is intentional — never auto-retry it."""
    rid = _make_run(test_db)
    calls = []
    with patch.object(forge_services, "schedule_task_run",
                      lambda **kw: (calls.append(kw), {"ok": True})[1]):
        res = forge_services.complete_trigger(
            agent_id="any", trace_id="t", run_id=rid,
            success=False, error="Cancelled by user.")
    assert res.get("auto_retried") is False
    assert calls == []


def test_auto_retry_stops_after_cap(test_db):
    """Once the task has failed too many times in the window, stop
    retrying — no retry storm on a genuinely broken task."""
    import uuid as _uuid
    from backend.forge.models import Run as _Run, RunStatus as _RS
    rid = _make_run(test_db)
    run = forge_services.get_run(rid)
    task_id, agent_id = run["task_id"], run["agent_id"]
    with forge_services._session() as db:
        for _ in range(3):
            db.add(_Run(id=_uuid.uuid4().hex[:12], agent_id=agent_id,
                        task_id=task_id, status=_RS.FAILED))
        db.commit()
    calls = []
    with patch.object(forge_services, "schedule_task_run",
                      lambda **kw: (calls.append(kw), {"ok": True})[1]):
        res = forge_services.complete_trigger(
            agent_id=agent_id, trace_id="t", run_id=rid,
            success=False, error="subprocess exited with code 1")
    assert res.get("auto_retried") is False
    assert calls == []


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
