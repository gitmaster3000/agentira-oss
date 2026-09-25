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
from unittest.mock import patch

import backend.db as bdb
import backend.models  # noqa: F401
import backend.forge.models  # noqa: F401
from backend import services as core_services
from backend.forge import workflow
from backend.models import Task, TaskPriority, Profile, Role, Status, Project, allow_task_write
from backend.forge.models import (
    Agent, ForgeRuntime, Run, RunStatus, RunOutcome, RuntimeStatus,
    TransitionEvent, GateEvaluation,
)


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


def test_column_ui_details_exposes_real_gates_and_prompts():
    # The read-only workflow UI reads gates from the SAME engine that blocks
    # moves (backend.gates), plus the hand-off prompt for each column.
    flow = workflow.system_workflow()
    ui = workflow.column_ui_details(flow)

    # in_progress → review: the real gates guarding that exit.
    ip = ui["in_progress"]
    assert ip["advance_to"] == "review"
    gate_names = {g["name"] for g in ip["gates"]}
    assert gate_names == {"dod_all_checked", "has_branch_or_pr"}
    assert all(g["description"] for g in ip["gates"])

    # review is entered by the reviewer role — its prompt template must surface.
    rv = ui["review"]
    assert rv["prompt_role"] == "reviewer"
    assert rv["prompt"].strip()

    # done is terminal (no advance) and entered by the documentation role.
    dn = ui["done"]
    assert dn["advance_to"] is None
    assert dn["gates"] == []
    assert dn["prompt_role"] == "documentation"


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
def db_session(pg):
    yield bdb.SessionLocal


def _mk_agent(db, name, runtime_id="rt1"):
    role = db.query(Role).first()
    prof = Profile(name=name, display_name=name, password_hash="", avatar_url="",
                   webhook_url="", roles=[role], api_key="k_" + name,
                   conductor_enabled=True)
    db.add(prof); db.flush()
    if not db.get(ForgeRuntime, runtime_id):
        db.add(ForgeRuntime(id=runtime_id, daemon_id="d", provider="claude",
                            binary_path="/tmp/c", status=RuntimeStatus.ONLINE))
        db.flush()
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
    kwargs = mock_dispatch.call_args.kwargs
    assert kwargs["task_id"] == task_id
    assert kwargs["agent_id"] == reviewer_id
    # AP-361 follow-up: the reviewer gets review hand-off instructions, not
    # the bare implementer prompt — with the task's branch substituted.
    assert "reviewing this task" in kwargs["extra_context"]
    assert "do NOT re-implement" in kwargs["extra_context"]
    assert "agent/x/task/y" in kwargs["extra_context"]     # {{BRANCH}}
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "review"
        assert t.assignee == "senior reviewer"


def test_implementer_prompt_unchanged_by_role_handoff(db_session):
    """The implementer's own dispatch (via prepare_task_run/schedule_task_run
    directly, not the workflow hand-off) still gets the bare task prompt —
    the role hand-off prompt is only added on top for the NEXT agent."""
    from backend.forge import services as forge_services
    pid, task_id, run_id, impl_id, _ = _setup_review_scenario(db_session)
    with db_session() as db:
        t = db.get(Task, task_id)
        prompt = forge_services._build_task_prompt(t)
    assert "reviewing this task" not in prompt
    assert "do NOT re-implement" not in prompt
    assert "Work on this task" in prompt


def test_missing_role_prompt_file_dispatches_without_block(db_session):
    """A role with no prompt file (user-definable roles are legal without
    one) still dispatches — just without the extra_context block."""
    pid, task_id, run_id, impl_id, reviewer_id = _setup_review_scenario(db_session)
    flow = workflow.system_workflow()
    flow.roles["reviewer"].prompt = "does_not_exist_prompt"
    with patch.object(workflow, "effective_workflow", return_value=flow), \
         patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "next123"}) as mock_dispatch:
        out = workflow.advance_after_run(run_id)
    assert out["advanced"] is True
    kwargs = mock_dispatch.call_args.kwargs
    assert kwargs["extra_context"] == ""


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
    """AP-402: re-processing the SAME run is a no-op — the driver already
    recorded a transition_events row for it (explicit fact), so a duplicate
    finish_run call (webhook retry, race) can't hand the task off twice."""
    pid, task_id, run_id, impl_id, reviewer_id = _setup_review_scenario(db_session)
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "next123"}) as mock_dispatch:
        first = workflow.advance_after_run(run_id)
        second = workflow.advance_after_run(run_id)
    assert first["advanced"] is True
    assert second == {"advanced": False, "reason": "already_handed_off"}
    mock_dispatch.assert_called_once()   # not re-dispatched on the replay


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

def _approve(db, pid, task_id, reviewer_name):
    """Record a TYPED reviewer approval verdict (WFE Phase 2) — the only
    signal the driver reads. Not a comment."""
    from backend.forge.repos import activities as activities_repo
    activities_repo.record_review_verdict(
        db, project_id=pid, task_id=task_id, actor=reviewer_name,
        verdict="approve", note="correct and complete")
    db.commit()


def _setup_review_success(db_session, *, with_approval=True,
                          reviewer_name="senior reviewer"):
    """A succeeded REVIEWER run on a task sitting in `review`.

    Post-incident fix (2026-07-04, PR #167 merged before its verdict): a
    clean run is no longer enough to merge — a TYPED reviewer approval verdict
    (`review_verdict`, via `submit_review`) is required as evidence. A forged
    `REVIEW: APPROVE` comment does nothing. `with_approval` defaults True so
    this fixture represents the normal "reviewer approved" path; pass False to
    reproduce the incident shape (a run finishes `succeeded` in review with no
    approval verdict logged)."""
    with db_session() as db:
        proj = core_services.create_project("P")
        pid = proj["id"]
        p = db.get(Project, pid)
        p.workflow_enabled = True
        p.repo_url = "file:///tmp/fake-remote.git"
        p.verify_cmd = "scripts/verify.sh"      # Loop v1 C6: required to merge
        db.commit()
        reviewer_id = _mk_agent(db, reviewer_name)
        _bind(db, reviewer_id, pid)
        t = Task(project_id=pid, title="Build feature",
                 status_id=_status_id(db, "review"),
                 priority=TaskPriority.HIGH, assignee=reviewer_name,
                 creator="system", branch="agent/x/task/y",
                 dod_items=json.dumps([{"text": "d", "checked": True}]))
        db.add(t); db.commit()
        run = Run(agent_id=reviewer_id, task_id=t.id, project_id=pid,
                  status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                  worktree_branch="agent/x/task/y")
        db.add(run); db.commit()
        if with_approval:
            _approve(db, pid, t.id, reviewer_name)
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


def test_review_success_without_approval_evidence_refuses_merge(db_session):
    """Incident fix regression: a run finishing `succeeded` in review is NOT
    itself approval evidence — without a typed reviewer verdict, the driver
    refuses to merge and posts a visible refusal."""
    pid, task_id, run_id = _setup_review_success(db_session, with_approval=False)
    with patch("backend.forge.services._dispatch_coro") as mock_dispatch:
        out = workflow.advance_after_run(run_id)
    assert out == {"advanced": False, "reason": "no_approval_evidence"}
    mock_dispatch.assert_not_called()
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "review"   # stays put
        from backend.models import Activity
        acts = db.query(Activity).filter(Activity.task_id == task_id).all()
        assert any("Merge refused" in (a.detail or "") for a in acts)


def test_forged_review_approve_comment_does_nothing(db_session):
    """WFE Phase 2: the comment-grep is DELETED. A free-text `REVIEW: APPROVE`
    comment — even one whose `actor` matches the reviewer — is NOT evidence.
    Only a typed `review_verdict` approves. The driver must refuse the merge."""
    pid, task_id, run_id = _setup_review_success(db_session, with_approval=False)
    with db_session() as db:
        from backend.models import Activity
        # The exact string the old grep matched, from the reviewer's actor.
        db.add(Activity(project_id=pid, task_id=task_id, actor="senior reviewer",
                        action="commented",
                        detail="REVIEW: APPROVE — looks great, merge it."))
        db.commit()
    with patch("backend.forge.services._dispatch_coro") as mock_dispatch:
        out = workflow.advance_after_run(run_id)
    assert out == {"advanced": False, "reason": "no_approval_evidence"}
    mock_dispatch.assert_not_called()


def test_evidence_gate_evaluation_recorded_on_approval(db_session):
    """The human_approval evidence check writes its OWN gate_evaluations row
    with the evidence snapshot — the human can open the driver's reasoning in
    the API, not just infer it. Approval → outcome=allow, snapshot present."""
    pid, task_id, run_id = _setup_review_success(db_session, with_approval=True)
    with patch("backend.forge.services._dispatch_coro",
               side_effect=lambda coro: coro.close()):
        workflow.advance_after_run(run_id)
    with db_session() as db:
        from backend.forge.models import GateEvaluation
        row = (db.query(GateEvaluation)
                 .filter(GateEvaluation.task_id == task_id,
                         GateEvaluation.gate_id == "evidence:human_approval")
                 .first())
        assert row is not None
        assert row.outcome == "allow"
        snap = json.loads(row.evidence_snapshot)
        assert snap["human_approval"]["present"] is True
        assert snap["human_approval"]["data"]["verdict"] == "approve"


def test_incident_unapproved_concurrent_task_not_merged(db_session):
    """Incident shape (2026-07-04, PR #167 merged 3 minutes before its
    REQUEST_CHANGES verdict): two tasks in review at once, one reviewer-
    approved and one still awaiting a verdict — only the approved task's
    branch is dispatched for merge."""
    pid_a, task_a, run_a = _setup_review_success(
        db_session, with_approval=True, reviewer_name="reviewer-a")
    pid_b, task_b, run_b = _setup_review_success(
        db_session, with_approval=False, reviewer_name="reviewer-b")

    sent = []
    with patch("backend.forge.services._dispatch_coro",
               side_effect=lambda coro: (sent.append(coro), coro.close())):
        out_a = workflow.advance_after_run(run_a)
        out_b = workflow.advance_after_run(run_b)

    assert out_a.get("integration_requested") is True
    assert out_b == {"advanced": False, "reason": "no_approval_evidence"}
    assert len(sent) == 1   # only the approved task's merge was dispatched


def test_complete_integration_ok_advances_to_done(db_session):
    pid, task_id, run_id = _setup_review_success(db_session)
    out = workflow.complete_integration(task_id=task_id, run_id=run_id,
                                        ok=True, reason="merged")
    assert out["advanced"] is True and out["to"] == "done"
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "done"


def test_complete_integration_failure_stays_with_reason(db_session):
    """Infrastructure failures (not in integrate.on_failure.hand_back_on)
    leave the task in review with the reason on the feed."""
    pid, task_id, run_id = _setup_review_success(db_session)
    out = workflow.complete_integration(
        task_id=task_id, run_id=run_id, ok=False,
        reason="push_failed: remote rejected")
    assert out["advanced"] is False
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "review"   # stays put
        from backend.models import Activity
        acts = db.query(Activity).filter(Activity.task_id == task_id).all()
        assert any("push_failed" in (a.detail or "") for a in acts)


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
    kwargs = mock_dispatch.call_args.kwargs
    assert kwargs["task_id"] == task_id
    assert kwargs["agent_id"] == doc_id
    assert "documenting this task" in kwargs["extra_context"]
    assert "agent/x/task/y" in kwargs["extra_context"]     # {{BRANCH}}


def test_integration_ok_without_doc_agent_skips_docs(db_session):
    pid, task_id, run_id = _setup_review_success(db_session)
    out = workflow.complete_integration(task_id=task_id, run_id=run_id,
                                        ok=True, reason="merged")
    assert out["advanced"] is True
    assert "docs_agent" not in out          # silently skipped, task still done
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "done"


# ── AP-404 Phase 0: transition_events + gate_evaluations audit trail ─────

def _events(db_session, task_id):
    with db_session() as db:
        return (db.query(TransitionEvent)
                  .filter(TransitionEvent.task_id == task_id)
                  .order_by(TransitionEvent.created_at).all())


def test_driver_noop_writes_a_transition_event(db_session):
    """A driver decision that does NOT advance the task is still a decision —
    it must be logged, not silent. no_role_agent is the simplest no-op."""
    _, task_id, run_id, *_ = _setup_review_scenario(db_session, with_reviewer=False)
    out = workflow.advance_after_run(run_id)
    assert out["reason"] == "no_role_agent"
    events = _events(db_session, task_id)
    assert len(events) == 1
    assert events[0].actor_type == "workflow"
    assert events[0].cause == f"run:{run_id}"
    assert events[0].result == "no_op:no_role_agent"


def test_gate_evaluation_recorded_for_driver_check(db_session):
    pid, task_id, run_id, *_ = _setup_review_scenario(db_session, dod_checked=False)
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "bounce1"}):
        workflow.advance_after_run(run_id)
    with db_session() as db:
        rows = (db.query(GateEvaluation)
                  .filter(GateEvaluation.task_id == task_id).all())
    assert len(rows) == 1
    assert rows[0].outcome == "block"
    assert rows[0].transition == "in_progress:review"
    snap = json.loads(rows[0].evidence_snapshot)
    assert "dod_items" in snap


def test_ap383_full_sequence_fires_and_is_fully_logged(db_session):
    """AP-383 regression: implement -> review -> rework (rejection) ->
    approve -> integrate, replayed end to end. Every driver decision along
    the way — including the rejection hand-back — writes a transition_events
    row, and the final integration still fires."""
    from backend.models import Activity
    with db_session() as db:
        proj = core_services.create_project("P")
        pid = proj["id"]
        p = db.get(Project, pid)
        p.workflow_enabled = True
        p.repo_url = "file:///tmp/fake-remote.git"
        p.verify_cmd = "scripts/verify.sh"      # Loop v1 C6: required to merge
        db.commit()
        impl_id = _mk_agent(db, "implementer-1")
        _bind(db, impl_id, pid)
        reviewer_id = _mk_agent(db, "senior reviewer")
        _bind(db, reviewer_id, pid)
        t = Task(project_id=pid, title="Build feature",
                 status_id=_status_id(db, "in_progress"),
                 priority=TaskPriority.HIGH, assignee="implementer-1",
                 creator="system", branch="agent/x/task/y",
                 dod_items=json.dumps([{"text": "d", "checked": True}]))
        db.add(t); db.commit()
        task_id = t.id

    # 1) implement -> review
    with db_session() as db:
        run1 = Run(agent_id=impl_id, task_id=task_id, project_id=pid,
                  status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED)
        db.add(run1); db.commit()
        run1_id = run1.id
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "r2"}):
        out1 = workflow.advance_after_run(run1_id)
    assert out1["advanced"] is True and out1["to"] == "review"

    # 2) reviewer rejects -> rework (hand-back to implementer)
    with db_session() as db:
        run2 = Run(agent_id=reviewer_id, task_id=task_id, project_id=pid,
                  status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED)
        db.add(run2); db.commit()
        run2_id = run2.id
        db.add(Activity(project_id=pid, task_id=task_id, actor="senior reviewer",
                        action="task.move", detail="review → in_progress",
                        diff=json.dumps({"status": {"from": "review",
                                                    "to": "in_progress"}})))
        db.add(Activity(project_id=pid, task_id=task_id, actor="senior reviewer",
                        action="commented", detail="Fix the flaky test first."))
        db.commit()
        t = db.get(Task, task_id)
        with allow_task_write():
            t.status_id = _status_id(db, "in_progress")
        db.commit()
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "r3"}) as mock_dispatch:
        out2 = workflow.advance_after_run(run2_id)
    assert out2["reason"] == "review_rejected"
    assert out2.get("handed_back") is True
    assert mock_dispatch.call_args.kwargs["agent_id"] == impl_id

    # 3) implementer reworks -> review again
    with db_session() as db:
        run3 = Run(agent_id=impl_id, task_id=task_id, project_id=pid,
                  status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED)
        db.add(run3); db.commit()
        run3_id = run3.id
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "r4"}):
        out3 = workflow.advance_after_run(run3_id)
    assert out3["advanced"] is True and out3["to"] == "review"

    # 4) reviewer approves -> integration requested (two-phase)
    with db_session() as db:
        run4 = Run(agent_id=reviewer_id, task_id=task_id, project_id=pid,
                  status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                  worktree_branch="agent/x/task/y")
        db.add(run4); db.commit()
        run4_id = run4.id
        _approve(db, pid, task_id, "senior reviewer")
    with patch("backend.forge.services._dispatch_coro",
               side_effect=lambda coro: coro.close()):
        out4 = workflow.advance_after_run(run4_id)
    assert out4.get("integration_requested") is True

    # 5) daemon reports the merge -> done
    out5 = workflow.complete_integration(task_id=task_id, run_id=run4_id,
                                         ok=True, reason="merged")
    assert out5["advanced"] is True and out5["to"] == "done"
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "done"

    # Every step along the way is in the audit trail — nothing silent.
    events = _events(db_session, task_id)
    causes = [e.cause for e in events]
    results = [e.result for e in events]
    assert causes == [f"run:{run1_id}", f"run:{run2_id}",
                      f"run:{run3_id}", f"run:{run4_id}", f"run:{run4_id}"]
    assert results == ["advanced", "handed_back", "advanced",
                       "integration_requested", "advanced"]


# ── Manual done→review re-entry must not poison the reviewer's verdict ────

def _log_move(db, pid, task_id, actor, src, dst):
    from backend.models import Activity
    db.add(Activity(project_id=pid, task_id=task_id, actor=actor,
                    action="task.move", detail=f"{src} → {dst}",
                    diff=json.dumps({"status": {"from": src, "to": dst}})))
    db.commit()


def test_manual_done_to_review_then_approve_integrates_not_rejects(db_session):
    """AP-379/AP-383 regression: an operator manually moves a task done→review
    to force a re-review. The reviewer then approves (REVIEW: APPROVE). The
    driver MUST read the reviewer's own verdict and request integration — it
    must NOT misread the backward done→review move as a rejection and bounce a
    corrective run to the implementer."""
    pid, task_id, run_id = _setup_review_success(db_session, with_approval=True)
    # The poison: a manual done→review move logged during the reviewer's run.
    with db_session() as db:
        _log_move(db, pid, task_id, "Claude-external", "done", "review")
    sent = []
    with patch("backend.forge.services._dispatch_coro",
               side_effect=lambda coro: (sent.append(coro), coro.close())), \
         patch("backend.forge.services.schedule_task_run") as mock_bounce:
        out = workflow.advance_after_run(run_id)
    assert out.get("integration_requested") is True    # merged, not bounced
    assert out.get("reason") != "review_rejected"
    mock_bounce.assert_not_called()                     # no corrective run
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "review"   # awaiting merge


def test_approve_after_prior_manual_bounce_still_merges(db_session):
    """Second observed shape: a manual done→review re-entry happened, the run
    still finishes with an APPROVE verdict — the verdict wins and the branch
    integrates (no sticky rejection classification from the entry move)."""
    pid, task_id, run_id = _setup_review_success(db_session, with_approval=True)
    with db_session() as db:
        # two backward re-entries, both before the approving verdict
        _log_move(db, pid, task_id, "Claude-external", "done", "review")
        _log_move(db, pid, task_id, "operator", "done", "review")
    with patch("backend.forge.services._dispatch_coro",
               side_effect=lambda coro: coro.close()), \
         patch("backend.forge.services.schedule_task_run") as mock_bounce:
        out = workflow.advance_after_run(run_id)
    assert out.get("integration_requested") is True
    mock_bounce.assert_not_called()


def test_ap383_sticky_reviewer_row_reapproval_integrates(db_session):
    """AP-383 deadlock regression (sticky runs, AP-281): one run row per
    agent+task, REUSED across turns — created_at never moves. Sequence:
    implementer -> reviewer rejects (driver logs a decision for the reviewer
    row) -> implementer reworks on its own reused row -> the SAME reviewer
    row starts a new turn and approves. The driver must integrate: the old
    turn's hand-back event and rejection move belong to a previous turn, not
    this one."""
    from datetime import datetime, timedelta, timezone
    with db_session() as db:
        proj = core_services.create_project("P")
        pid = proj["id"]
        p = db.get(Project, pid)
        p.workflow_enabled = True
        p.repo_url = "file:///tmp/fake-remote.git"
        p.verify_cmd = "scripts/verify.sh"
        db.commit()
        impl_id = _mk_agent(db, "implementer-1")
        _bind(db, impl_id, pid)
        reviewer_id = _mk_agent(db, "senior reviewer")
        _bind(db, reviewer_id, pid)
        t = Task(project_id=pid, title="Build feature",
                 status_id=_status_id(db, "in_progress"),
                 priority=TaskPriority.HIGH, assignee="implementer-1",
                 creator="system", branch="agent/x/task/y",
                 dod_items=json.dumps([{"text": "d", "checked": True}]))
        db.add(t); db.commit()
        task_id = t.id
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        impl_run = Run(agent_id=impl_id, task_id=task_id, project_id=pid,
                       status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                       created_at=start, started_at=start)
        db.add(impl_run); db.commit()
        impl_run_id = impl_run.id

    # 1) implement -> review
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "rv"}):
        assert workflow.advance_after_run(impl_run_id)["to"] == "review"

    # 2) reviewer's (sticky) row, first turn: rejects
    with db_session() as db:
        rv_start = start + timedelta(minutes=10)
        rv = Run(agent_id=reviewer_id, task_id=task_id, project_id=pid,
                 status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                 worktree_branch="agent/x/task/y",
                 created_at=rv_start, started_at=rv_start)
        db.add(rv); db.commit()
        rv_id = rv.id
        _log_move(db, pid, task_id, "senior reviewer", "review", "in_progress")
        t = db.get(Task, task_id)
        with allow_task_write():
            t.status_id = _status_id(db, "in_progress")
        db.commit()
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": impl_run_id}):
        assert workflow.advance_after_run(rv_id).get("handed_back") is True

    # 3) implementer's SAME row, new turn: rework -> review
    with db_session() as db:
        r = db.get(Run, impl_run_id)
        r.started_at = datetime.now(timezone.utc)
        r.outcome = RunOutcome.SUCCEEDED
        db.commit()
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": rv_id}):
        out3 = workflow.advance_after_run(impl_run_id)
    assert out3["advanced"] is True and out3["to"] == "review"

    # 4) reviewer's SAME row, new turn: approves -> must integrate
    with db_session() as db:
        r = db.get(Run, rv_id)
        r.started_at = datetime.now(timezone.utc)
        r.outcome = RunOutcome.SUCCEEDED
        db.commit()
        _approve(db, pid, task_id, "senior reviewer")
    with patch("backend.forge.services._dispatch_coro",
               side_effect=lambda coro: coro.close()), \
         patch("backend.forge.services.schedule_task_run") as mock_bounce:
        out4 = workflow.advance_after_run(rv_id)
    assert out4.get("integration_requested") is True, out4
    mock_bounce.assert_not_called()

    # Replaying the same turn is still a no-op (AP-402 intent preserved).
    assert workflow.advance_after_run(rv_id) == {
        "advanced": False, "reason": "already_handed_off"}


# ── Loop v1 C5: merge into the repo's base branch, never a literal main ──

def _add_primary_repo(db_session, pid, default_branch):
    from backend.models import ProjectRepo
    with db_session() as db:
        db.add(ProjectRepo(project_id=pid, name="app", repo_path="",
                           repo_url="file:///tmp/fake-remote.git",
                           default_branch=default_branch, is_primary=True))
        db.commit()


def _capture_integrate():
    from unittest.mock import MagicMock
    from backend.forge.ws_dispatch import hub
    fake = MagicMock(return_value=None)
    return fake, patch.object(hub, "dispatch_integrate", fake), \
        patch("backend.forge.services._dispatch_coro", lambda coro: None)


def test_integration_targets_repo_default_branch(db_session):
    pid, task_id, run_id = _setup_review_success(db_session)
    _add_primary_repo(db_session, pid, "main-rsi")
    fake, p1, p2 = _capture_integrate()
    with p1, p2:
        out = workflow.advance_after_run(run_id)
    assert out.get("integration_requested") is True
    assert fake.call_args.kwargs["target_branch"] == "main-rsi"


def test_integration_refused_when_task_has_no_repo(db_session):
    """No repo row and no legacy repo fields → nothing to merge into: refuse
    with a reason, never guess a branch."""
    pid, task_id, run_id = _setup_review_success(db_session)
    with db_session() as db:
        db.get(Project, pid).repo_url = None
        db.commit()
    fake, p1, p2 = _capture_integrate()
    with p1, p2:
        out = workflow.advance_after_run(run_id)
    assert out["reason"] == "integration_missing_info"
    fake.assert_not_called()



# ── Loop v1 C6: merged-tree verification decides the merge ───────────────

def _setup_reworked_review(db_session):
    """Implementer ran first, then the reviewer's succeeded run in review —
    so a hand-back has someone to go to."""
    pid, task_id, run_id = _setup_review_success(db_session)
    with db_session() as db:
        impl_id = _mk_agent(db, "implementer-1")
        _bind(db, impl_id, pid)
        review_run = db.get(Run, run_id)
        from datetime import timedelta
        db.add(Run(agent_id=impl_id, task_id=task_id, project_id=pid,
                   status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                   created_at=review_run.created_at - timedelta(minutes=5)))
        db.commit()
    return pid, task_id, run_id, impl_id


def test_merge_refused_without_verify_cmd(db_session):
    pid, task_id, run_id = _setup_review_success(db_session)
    with db_session() as db:
        db.get(Project, pid).verify_cmd = ""
        db.commit()
    fake, p1, p2 = _capture_integrate()
    with p1, p2:
        out = workflow.advance_after_run(run_id)
    assert out["reason"] == "no_verify_cmd"
    fake.assert_not_called()
    with db_session() as db:
        from backend.models import Activity
        acts = db.query(Activity).filter(Activity.task_id == task_id).all()
        assert any("no verify command" in (a.detail or "") for a in acts)


def test_integrate_carries_verify_cmd_and_timeout(db_session):
    pid, task_id, run_id = _setup_review_success(db_session)
    with db_session() as db:
        db.get(Project, pid).verify_timeout_minutes = 20
        db.commit()
    fake, p1, p2 = _capture_integrate()
    with p1, p2:
        workflow.advance_after_run(run_id)
    kw = fake.call_args.kwargs
    assert kw["verify_cmd"] == "scripts/verify.sh" and kw["verify_timeout_s"] == 1200


def test_verify_failure_hands_back_to_implementer_with_output(db_session):
    pid, task_id, run_id, impl_id = _setup_reworked_review(db_session)
    verify = {"exit_code": 1, "duration_s": 9.0, "timed_out": False,
              "log_tail": "FAILED test_x - AssertionError: boom"}
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "fix1"}) as sched:
        workflow.complete_integration(task_id=task_id, run_id=run_id, ok=False,
                                      reason="verify_failed: exit 1", verify=verify)
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "in_progress"
        assert t.assignee == "implementer-1"
        from backend.forge.models import GateEvaluation
        ev = (db.query(GateEvaluation)
                .filter(GateEvaluation.task_id == task_id,
                        GateEvaluation.gate_id == "evidence:tests").all())
        assert [e.outcome for e in ev] == ["block"]
    assert sched.call_args.kwargs["agent_id"] == impl_id
    assert "AssertionError: boom" in sched.call_args.kwargs["extra_context"]


def test_verify_pass_records_evidence_and_advances(db_session):
    pid, task_id, run_id = _setup_review_success(db_session)
    verify = {"exit_code": 0, "duration_s": 3.0, "timed_out": False, "log_tail": "ok"}
    out = workflow.complete_integration(task_id=task_id, run_id=run_id, ok=True,
                                        reason="merged", verify=verify)
    assert out["advanced"] is True
    with db_session() as db:
        from backend.forge.models import GateEvaluation
        ev = (db.query(GateEvaluation)
                .filter(GateEvaluation.task_id == task_id,
                        GateEvaluation.gate_id == "evidence:tests").all())
        assert [e.outcome for e in ev] == ["allow"]


# ── Loop v1 C6: the policy above comes from the workflow YAML, not code ──

def _flow_with_integrate(**integrate_overrides):
    """The system flow with the review column's integrate policy edited —
    what a different workflow YAML would produce."""
    flow = workflow.system_workflow().copy(deep=True)
    col = flow.column("review")
    col.on_success.integrate = col.on_success.integrate.copy(update=integrate_overrides)
    return flow


def test_system_yaml_declares_integration_policy():
    spec = workflow.system_workflow().column("review").on_success.integrate
    assert spec.verify.required is True
    assert "verify_failed" in spec.on_failure.hand_back_on
    assert spec.on_failure.to_column == "in_progress"


def test_verify_not_required_by_flow_merges_without_command(db_session):
    pid, task_id, run_id = _setup_review_success(db_session)
    with db_session() as db:
        db.get(Project, pid).verify_cmd = ""
        db.commit()
    flow = _flow_with_integrate(verify=workflow.VerifySpec(required=False))
    fake, p1, p2 = _capture_integrate()
    with p1, p2, patch.object(workflow, "system_workflow", return_value=flow):
        out = workflow.advance_after_run(run_id)
    assert out.get("integration_requested") is True
    assert fake.call_args.kwargs["verify_cmd"] == ""


def test_failure_kind_not_listed_in_yaml_stays_put(db_session):
    pid, task_id, run_id, _ = _setup_reworked_review(db_session)
    flow = _flow_with_integrate(on_failure=workflow.IntegrationFailureSpec(
        hand_back_on=["verify_failed"], to_column="in_progress"))
    with patch.object(workflow, "system_workflow", return_value=flow), \
         patch("backend.forge.services.schedule_task_run") as sched:
        workflow.complete_integration(task_id=task_id, run_id=run_id, ok=False,
                                      reason="merge_conflict: a.txt")
    sched.assert_not_called()
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "review"


def test_on_failure_to_unknown_column_is_rejected_at_parse():
    import yaml
    raw = yaml.safe_load(open(workflow._DEFAULT_WORKFLOW_PATH))
    for c in raw["columns"]:
        if c["name"] == "review":
            c["on_success"]["integrate"]["on_failure"]["to_column"] = "nowhere"
    with pytest.raises(Exception):
        workflow.Workflow(**raw)


def test_integration_hand_back_is_not_worded_as_a_review_rejection(db_session):
    pid, task_id, run_id, _ = _setup_reworked_review(db_session)
    with patch("backend.forge.services.schedule_task_run", return_value={"run_id": "x"}):
        workflow.complete_integration(
            task_id=task_id, run_id=run_id, ok=False, reason="verify_failed: exit 2",
            verify={"exit_code": 2, "duration_s": 1, "timed_out": False, "log_tail": "E"})
    with db_session() as db:
        from backend.models import Activity
        details = [a.detail or "" for a in
                   db.query(Activity).filter(Activity.task_id == task_id).all()]
    assert any("Merge failed — handed back to implementer-1" in d for d in details)
    assert not any("Review rejected" in d for d in details)


# ── AP-520/521: integrate merges the task's WORK branch ──────────────────

def test_review_approval_integrates_implementer_branch_not_reviewers(db_session):
    """AP-520: the approving run is the REVIEWER's — its own worktree branch
    has no work on it. The merge must carry the implementer's branch."""
    pid, task_id, run_id = _setup_review_success(db_session)
    with db_session() as db:
        db.get(Task, task_id).branch = "agent/impl/task/t1"
        db.get(Run, run_id).worktree_branch = "agent/reviewer/task/t1"
        db.commit()
    _add_primary_repo(db_session, pid, "main")
    fake, p1, p2 = _capture_integrate()
    with p1, p2:
        out = workflow.advance_after_run(run_id)
    assert out.get("integration_requested") is True
    assert fake.call_args.kwargs["branch"] == "agent/impl/task/t1"


def test_review_run_branch_never_used_when_task_has_no_branch(db_session):
    """No work branch on the task and the finishing run is a review hand-off
    (someone else succeeded before it) → refuse, never merge the reviewer's
    empty branch."""
    pid, task_id, run_id, impl_id = _setup_reworked_review(db_session)
    with db_session() as db:
        db.get(Task, task_id).branch = ""
        db.get(Run, run_id).worktree_branch = "agent/reviewer/task/t1"
        db.commit()
    _add_primary_repo(db_session, pid, "main")
    fake, p1, p2 = _capture_integrate()
    with p1, p2:
        out = workflow.advance_after_run(run_id)
    assert out["reason"] == "integration_missing_info"
    fake.assert_not_called()


def test_task_branch_follows_succeeded_run_after_failed_first_run(db_session):
    """AP-521: the first run (out of credits) pinned task.branch to its own
    empty branch and failed. Another agent's succeeded run is the real work —
    task.branch must follow it."""
    pid, task_id, run_id, impl_id, _ = _setup_review_scenario(db_session)
    with db_session() as db:
        from datetime import timedelta
        work = db.get(Run, run_id)
        work.worktree_branch = "agent/coder2/task/t1"
        first_id = _mk_agent(db, "best coder")
        db.add(Run(agent_id=first_id, task_id=task_id, project_id=pid,
                   status=RunStatus.COMPLETED, outcome=RunOutcome.FAILED,
                   worktree_branch="agent/coder1/task/t1",
                   created_at=work.created_at - timedelta(minutes=5)))
        db.get(Task, task_id).branch = "agent/coder1/task/t1"
        db.commit()
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "next123"}) as mock_dispatch:
        workflow.advance_after_run(run_id)
    with db_session() as db:
        assert db.get(Task, task_id).branch == "agent/coder2/task/t1"
    # The reviewer is pointed at the real work branch too.
    assert "agent/coder2/task/t1" in mock_dispatch.call_args.kwargs["extra_context"]


def test_human_set_branch_is_not_clobbered_by_run_branch(db_session):
    """A branch no run produced (human/PR link) is left alone."""
    pid, task_id, run_id, impl_id, _ = _setup_review_scenario(db_session)
    with db_session() as db:
        db.get(Run, run_id).worktree_branch = "agent/impl/task/t1"
        db.get(Task, task_id).branch = "feature/human-work"
        db.commit()
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "next123"}):
        workflow.advance_after_run(run_id)
    with db_session() as db:
        assert db.get(Task, task_id).branch == "feature/human-work"


def test_task_branch_follows_succeeded_run_even_when_workflow_disabled(db_session):
    """Branch bookkeeping is not a workflow-driver feature: a stale pinned
    branch is corrected regardless of workflow_enabled."""
    pid, task_id, run_id, impl_id, _ = _setup_review_scenario(
        db_session, enabled=False)
    with db_session() as db:
        work = db.get(Run, run_id)
        work.worktree_branch = "agent/coder2/task/t1"
        from datetime import timedelta
        first_id = _mk_agent(db, "best coder")
        db.add(Run(agent_id=first_id, task_id=task_id, project_id=pid,
                   status=RunStatus.COMPLETED, outcome=RunOutcome.FAILED,
                   worktree_branch="agent/coder1/task/t1",
                   created_at=work.created_at - timedelta(minutes=5)))
        db.get(Task, task_id).branch = "agent/coder1/task/t1"
        db.commit()
    workflow.advance_after_run(run_id)
    with db_session() as db:
        assert db.get(Task, task_id).branch == "agent/coder2/task/t1"
