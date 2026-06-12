"""Workflow driver — the self-sufficiency loop (config-validated).

Covers the locked design rules:
- system flow parses via yaml.safe_load + Pydantic and defines the pipeline;
- the CUSTOMER surface is roles-only (workflow_roles_json) — a malformed
  override is ignored, never fatal, and can't rewire columns;
- reviewer != implementer is config (exclude_previous_assignee);
- advance_after_run: opt-in, gate-checked, idempotent, hands the task to the
  next column's role agent.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

import backend.models  # noqa: F401
import backend.forge.models  # noqa: F401
from backend.db import Base
from backend import services as core_services
from backend.forge import workflow
from backend.models import Task, TaskPriority, Profile, Role, Status, Project
from backend.forge.models import Agent, Run, RunStatus, RunOutcome


# ── Schema / config layering ─────────────────────────────────────────────

def test_system_workflow_parses_and_pins_pipeline():
    flow = workflow.system_workflow()
    names = [c.name for c in flow.columns]
    assert names == ["backlog", "todo", "in_progress", "review", "done"]
    ip = flow.column("in_progress")
    assert ip.on_success.advance_to == "review"
    assert ip.on_success.assign_role == "reviewer"
    assert ip.on_success.dispatch is True
    reviewer = flow.roles["reviewer"]
    assert reviewer.exclude_previous_assignee is True   # reviewer != implementer
    assert reviewer.fallback == "none"
    # AP-252: rejection hand-back is YAML policy, not code constants.
    assert flow.rejection.enabled is True
    assert flow.rejection.assign == "previous_agent"
    assert flow.rejection.dispatch is True
    assert flow.rejection.prompt == "rejection_handback"


def test_customer_override_is_roles_only_and_validated():
    class P:
        id = "p1"
        workflow_roles_json = json.dumps({
            "reviewer": {"match": ["qa"], "exclude_previous_assignee": True},
        })
    flow = workflow.effective_workflow(P())
    assert flow.roles["reviewer"].match == ["qa"]          # override applied
    assert [c.name for c in flow.columns] == [             # columns untouched
        "backlog", "todo", "in_progress", "review", "done"]


def test_malformed_override_is_ignored_not_fatal():
    class P:
        id = "p1"
        workflow_roles_json = '{"reviewer": {"fallback": "bogus"}}'
    flow = workflow.effective_workflow(P())
    assert flow.roles["reviewer"].fallback == "none"       # system value kept

    class P2:
        id = "p2"
        workflow_roles_json = "not json at all"
    assert workflow.effective_workflow(P2()).roles["reviewer"].fallback == "none"


# ── DB-backed driver tests ───────────────────────────────────────────────

@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.workflow.SessionLocal", TestSession):
        s = TestSession()
        core_services._seed_defaults(s)
        s.close()
        yield TestSession


def _mk_agent(db, name, runtime_id="rt1"):
    role = db.query(Role).first()
    prof = Profile(name=name, display_name=name, password_hash="", avatar_url="",
                   webhook_url="", role_id=role.id, api_key="k_" + name,
                   conductor_enabled=True)
    db.add(prof); db.flush()
    agent = Agent(id=prof.id, profile_id=prof.id, name=name, runtime_id=runtime_id)
    db.add(agent); db.commit()
    return agent.id


def _bind(db, agent_id, project_id):
    prof = db.get(Profile, agent_id)
    prof.default_project_id = project_id
    db.commit()


def _status_id(db, name):
    return db.query(Status).filter(Status.name == name).first().id


def _setup_review_scenario(db_session, *, with_reviewer=True, enabled=True,
                           dod_checked=True):
    """A succeeded implementer run on an in_progress task with branch+DoD."""
    with db_session() as db:
        proj = core_services.create_project("P")
        pid = proj["id"]
        p = db.get(Project, pid)
        p.workflow_enabled = enabled
        db.commit()
        impl_id = _mk_agent(db, "implementer-1")
        _bind(db, impl_id, pid)
        reviewer_id = None
        if with_reviewer:
            reviewer_id = _mk_agent(db, "senior reviewer")
            _bind(db, reviewer_id, pid)
        dod = [{"text": "done it", "checked": bool(dod_checked)}]
        t = Task(project_id=pid, title="Build feature",
                 status_id=_status_id(db, "in_progress"),
                 priority=TaskPriority.HIGH, assignee="implementer-1",
                 creator="system", branch="agent/x/task/y",
                 dod_items=json.dumps(dod))
        db.add(t); db.commit()
        run = Run(agent_id=impl_id, task_id=t.id, project_id=pid,
                  status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED)
        db.add(run); db.commit()
        return pid, t.id, run.id, impl_id, reviewer_id


def test_advance_hands_off_to_reviewer(db_session):
    pid, task_id, run_id, impl_id, reviewer_id = _setup_review_scenario(db_session)
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "next123"}) as mock_dispatch:
        out = workflow.advance_after_run(run_id)
    assert out["advanced"] is True
    assert out["to"] == "review"
    assert out["assignee"] == "senior reviewer"           # != implementer
    assert out["run_id"] == "next123"
    mock_dispatch.assert_called_once_with(task_id=task_id, agent_id=reviewer_id)
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "review"
        assert t.assignee == "senior reviewer"


def test_no_advance_when_workflow_disabled(db_session):
    _, task_id, run_id, *_ = _setup_review_scenario(db_session, enabled=False)
    out = workflow.advance_after_run(run_id)
    assert out == {"advanced": False, "reason": "workflow_disabled"}
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "in_progress"


def test_no_advance_without_distinct_reviewer(db_session):
    """reviewer != implementer (config): with only the implementer bound,
    the task stays in in_progress rather than self-reviewing."""
    _, task_id, run_id, *_ = _setup_review_scenario(db_session, with_reviewer=False)
    out = workflow.advance_after_run(run_id)
    assert out["advanced"] is False
    assert out["reason"] == "no_role_agent"
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "in_progress"


def test_gate_blocks_advance_when_dod_unchecked(db_session):
    """The driver respects the same evidence as a manual move — unchecked DoD
    fails the in_progress->review gate. AP-231: instead of stalling silently,
    it bounces the task back to the same agent once (a corrective dispatch)."""
    pid, task_id, run_id, *_ = _setup_review_scenario(db_session, dod_checked=False)
    with db_session() as db:
        p = db.get(Project, pid)
        p.gates_enabled = True   # documents intent; gates.evaluate is direct
        db.commit()
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "bounce1"}) as mock_dispatch:
        out = workflow.advance_after_run(run_id)
    assert out["advanced"] is False
    assert out["reason"] == "gate_failed"
    assert "dod_all_checked" in out["failures"]
    # AP-231: bounced (one corrective re-dispatch), not silently stalled.
    assert out.get("bounced") is True
    assert out.get("bounce_run_id") == "bounce1"
    mock_dispatch.assert_called_once()


def test_bounce_exhausted_escalates_to_needs_attention(db_session):
    """After the configured bounce budget (default 2 runs in window), the
    task escalates to needs-attention instead of bouncing forever."""
    pid, task_id, run_id, impl_id, _ = _setup_review_scenario(db_session, dod_checked=False)
    # A PRIOR (older) run so this (task, agent) is already at max_attempts=2.
    # Older than the advancing run so the idempotency guard doesn't trip.
    from datetime import datetime, timezone, timedelta
    with db_session() as db:
        db.add(Run(agent_id=impl_id, task_id=task_id, project_id=pid,
                   status=RunStatus.FAILED, outcome=RunOutcome.FAILED,
                   created_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
        db.commit()
    with patch("backend.forge.services.schedule_task_run") as mock_dispatch:
        out = workflow.advance_after_run(run_id)
    assert out["reason"] == "gate_failed"
    assert out.get("escalated") is True
    assert out.get("bounced") is not True
    mock_dispatch.assert_not_called()   # no more bounces — escalated
    with db_session() as db:
        from backend.models import Activity
        acts = db.query(Activity).filter(Activity.task_id == task_id).all()
        assert any("Needs attention" in (a.detail or "") for a in acts)


def test_idempotent_no_double_handoff(db_session):
    """A newer run on the task means this run's hand-off already happened."""
    pid, task_id, run_id, impl_id, _ = _setup_review_scenario(db_session)
    with db_session() as db:
        db.add(Run(agent_id=impl_id, task_id=task_id, project_id=pid,
                   status=RunStatus.RUNNING))
        db.commit()
    out = workflow.advance_after_run(run_id)
    assert out == {"advanced": False, "reason": "already_handed_off"}


def test_failed_run_never_advances(db_session):
    pid, task_id, run_id, impl_id, _ = _setup_review_scenario(db_session)
    with db_session() as db:
        r = db.get(Run, run_id)
        r.outcome = RunOutcome.FAILED
        db.commit()
    out = workflow.advance_after_run(run_id)
    assert out["advanced"] is False


# ── AP-252: reviewer rejection hands back to the implementer ─────────────

def _setup_rejection_scenario(db_session, *, with_prior_impl_run=True):
    """A reviewer run that succeeded AFTER demoting the task review→
    in_progress (rejection). The exact SP-12 live sequence: DoD unchecked,
    task back in in_progress, reviewer's run finishes succeeded."""
    from datetime import datetime, timezone, timedelta
    from backend.models import Activity
    with db_session() as db:
        proj = core_services.create_project("P")
        pid = proj["id"]
        p = db.get(Project, pid)
        p.workflow_enabled = True
        db.commit()
        impl_id = _mk_agent(db, "implementer-1")
        _bind(db, impl_id, pid)
        reviewer_id = _mk_agent(db, "senior reviewer")
        _bind(db, reviewer_id, pid)
        t = Task(project_id=pid, title="Build feature",
                 status_id=_status_id(db, "in_progress"),   # demoted
                 priority=TaskPriority.HIGH, assignee="senior reviewer",
                 creator="system", branch="agent/x/task/y",
                 dod_items=json.dumps([{"text": "d", "checked": False}]))
        db.add(t); db.commit()
        now = datetime.now(timezone.utc)
        if with_prior_impl_run:
            # The implementer's run — outside the bounce window so the
            # hand-back budget isn't already spent.
            db.add(Run(agent_id=impl_id, task_id=t.id, project_id=pid,
                       status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                       created_at=now - timedelta(hours=2)))
        run = Run(agent_id=reviewer_id, task_id=t.id, project_id=pid,
                  status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                  created_at=now - timedelta(minutes=5))
        db.add(run); db.commit()
        # The rejection, logged during the reviewer's run.
        db.add(Activity(project_id=pid, task_id=t.id, actor="senior reviewer",
                        action="task.move", detail="review → in_progress",
                        diff=json.dumps({"status": {"from": "review",
                                                    "to": "in_progress"}})))
        db.add(Activity(project_id=pid, task_id=t.id, actor="senior reviewer",
                        action="commented",
                        detail="Claimed commit d896cb2 does not exist."))
        db.commit()
        return pid, t.id, run.id, impl_id, reviewer_id


def test_reviewer_rejection_hands_back_to_implementer(db_session):
    """AP-252 regression: the corrective run goes to the IMPLEMENTER with the
    reviewer's feedback — never bounced back to the reviewer."""
    pid, task_id, run_id, impl_id, reviewer_id = \
        _setup_rejection_scenario(db_session)
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "fix1"}) as mock_dispatch:
        out = workflow.advance_after_run(run_id)
    assert out["reason"] == "review_rejected"
    assert out.get("handed_back") is True
    assert out["assignee"] == "implementer-1"
    kwargs = mock_dispatch.call_args.kwargs
    assert kwargs["agent_id"] == impl_id            # NOT the reviewer
    assert "d896cb2" in kwargs["extra_context"]     # feedback carried over
    with db_session() as db:
        t = db.get(Task, task_id)
        assert t.assignee == "implementer-1"
        assert db.get(Status, t.status_id).name == "in_progress"  # stays put


def test_rejection_without_prior_implementer_escalates(db_session):
    """No implementer run to hand back to → needs-attention, not a bounce."""
    pid, task_id, run_id, *_ = _setup_rejection_scenario(
        db_session, with_prior_impl_run=False)
    with patch("backend.forge.services.schedule_task_run") as mock_dispatch:
        out = workflow.advance_after_run(run_id)
    assert out["reason"] == "review_rejected"
    assert out.get("escalated") is True
    mock_dispatch.assert_not_called()


def test_rejection_policy_disabled_skips_handback(db_session):
    """rejection.enabled=false (config) → driver skips the advance and leaves
    recovery to the watchdog — no dispatch, no reassignment."""
    pid, task_id, run_id, *_ = _setup_rejection_scenario(db_session)
    flow = workflow.system_workflow()
    flow.rejection.enabled = False
    with patch.object(workflow, "effective_workflow", return_value=flow), \
         patch("backend.forge.services.schedule_task_run") as mock_dispatch:
        out = workflow.advance_after_run(run_id)
    assert out["reason"] == "review_rejected"
    assert out.get("handed_back") is False
    mock_dispatch.assert_not_called()


def test_rejection_handback_budget_exhausted_escalates(db_session):
    """Two implementer runs already inside the window → no ping-pong; the
    task escalates to a human instead of looping implementer↔reviewer."""
    from datetime import datetime, timezone, timedelta
    pid, task_id, run_id, impl_id, _ = _setup_rejection_scenario(db_session)
    with db_session() as db:
        now = datetime.now(timezone.utc)
        for mins in (20, 10):
            db.add(Run(agent_id=impl_id, task_id=task_id, project_id=pid,
                       status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                       created_at=now - timedelta(minutes=mins)))
        db.commit()
    with patch("backend.forge.services.schedule_task_run") as mock_dispatch:
        out = workflow.advance_after_run(run_id)
    assert out["reason"] == "review_rejected"
    assert out.get("escalated") is True
    mock_dispatch.assert_not_called()


# ── Slice 2: two-phase integration (review -> done via daemon merge) ─────

def _setup_review_success(db_session):
    """A succeeded REVIEWER run on a task sitting in `review`."""
    with db_session() as db:
        proj = core_services.create_project("P")
        pid = proj["id"]
        p = db.get(Project, pid)
        p.workflow_enabled = True
        p.repo_url = "file:///tmp/fake-remote.git"
        db.commit()
        reviewer_id = _mk_agent(db, "senior reviewer")
        _bind(db, reviewer_id, pid)
        t = Task(project_id=pid, title="Build feature",
                 status_id=_status_id(db, "review"),
                 priority=TaskPriority.HIGH, assignee="senior reviewer",
                 creator="system", branch="agent/x/task/y",
                 dod_items=json.dumps([{"text": "d", "checked": True}]))
        db.add(t); db.commit()
        run = Run(agent_id=reviewer_id, task_id=t.id, project_id=pid,
                  status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                  worktree_branch="agent/x/task/y")
        db.add(run); db.commit()
        return pid, t.id, run.id


def test_review_success_requests_integration_not_advance(db_session):
    pid, task_id, run_id = _setup_review_success(db_session)
    sent = []
    with patch("backend.forge.services._dispatch_coro",
               side_effect=lambda coro: (sent.append(coro), coro.close())):
        out = workflow.advance_after_run(run_id)
    assert out.get("integration_requested") is True
    assert out["advanced"] is False
    assert len(sent) == 1
    with db_session() as db:   # not advanced yet — two-phase
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "review"


def test_complete_integration_ok_advances_to_done(db_session):
    pid, task_id, run_id = _setup_review_success(db_session)
    out = workflow.complete_integration(task_id=task_id, run_id=run_id,
                                        ok=True, reason="merged")
    assert out["advanced"] is True and out["to"] == "done"
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "done"


def test_complete_integration_failure_stays_with_reason(db_session):
    pid, task_id, run_id = _setup_review_success(db_session)
    out = workflow.complete_integration(
        task_id=task_id, run_id=run_id, ok=False,
        reason="merge_conflict: same.txt")
    assert out["advanced"] is False
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "review"   # stays put
        from backend.models import Activity
        acts = db.query(Activity).filter(Activity.task_id == task_id).all()
        assert any("merge_conflict" in (a.detail or "") for a in acts)


# ── Slice 3: documentation dispatched on arrival in done ─────────────────

def test_integration_ok_dispatches_documentation_role(db_session):
    pid, task_id, run_id = _setup_review_success(db_session)
    with db_session() as db:
        doc_id = _mk_agent(db, "Documentation Expert")
        _bind(db, doc_id, pid)
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "docs1"}) as mock_dispatch:
        out = workflow.complete_integration(task_id=task_id, run_id=run_id,
                                            ok=True, reason="merged")
    assert out["advanced"] is True and out["to"] == "done"
    assert out.get("docs_agent") == "Documentation Expert"
    assert out.get("docs_run_id") == "docs1"
    mock_dispatch.assert_called_once()


def test_integration_ok_without_doc_agent_skips_docs(db_session):
    pid, task_id, run_id = _setup_review_success(db_session)
    out = workflow.complete_integration(task_id=task_id, run_id=run_id,
                                        ok=True, reason="merged")
    assert out["advanced"] is True
    assert "docs_agent" not in out          # silently skipped, task still done
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "done"
