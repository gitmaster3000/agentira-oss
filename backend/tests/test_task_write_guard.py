"""Architectural invariant: Task.status_id/assignee only through TaskService.

Direct ORM writes to these two fields bypass auth (AP-374), gate checks, and
activity logging (AP-375) all at once — this is exactly what let a
non-project-member agent silently take over a task during an AP-361-style
reviewer hand-off. Covers:

  - the runtime guard (models.allow_task_write / event listeners) raises on
    a raw write to a persistent Task row, but not through TaskService;
  - the workflow driver's three former bypass sites (rejection hand-back,
    gate advance, integrate-complete) now route through
    update_task/move_task with actor="workflow", and every state change
    lands in the activity trail with that actor;
  - a hand-back target that is no longer a project member is rejected,
    not silently assigned.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import patch

import backend.db as bdb
import backend.models  # noqa: F401
import backend.forge.models  # noqa: F401
from backend import services as core_services
from backend.forge import workflow
from backend.models import Task, TaskPriority, Profile, Role, Status, Project, Activity
from backend.forge.models import Agent, ForgeRuntime, Run, RunStatus, RunOutcome, RuntimeStatus


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


# ── Runtime guard ─────────────────────────────────────────────────────────

def test_direct_assignee_write_on_persistent_task_raises(db_session):
    with db_session() as db:
        proj = core_services.create_project("P")
        t = Task(project_id=proj["id"], title="T",
                 status_id=_status_id(db, "backlog"), creator="system")
        db.add(t)
        db.commit()
        with pytest.raises(RuntimeError):
            t.assignee = "someone"


def test_direct_status_write_on_persistent_task_raises(db_session):
    with db_session() as db:
        proj = core_services.create_project("P")
        t = Task(project_id=proj["id"], title="T",
                 status_id=_status_id(db, "backlog"), creator="system")
        db.add(t)
        db.commit()
        with pytest.raises(RuntimeError):
            t.status_id = _status_id(db, "todo")


def test_taskservice_paths_still_work_under_the_guard(pg):
    """update_task/move_task mutate the same two fields — they must still
    succeed (they write inside allow_task_write())."""
    proj = core_services.create_project("P")
    core_services.create_profile("alice", role="member")
    core_services.add_project_member(proj["id"], "alice")
    t = core_services.create_task(proj["id"], "T", actor="system",
                                  dod_items=[{"text": "x", "checked": True}])
    core_services.update_task(t["id"], assignee="alice")
    assert core_services.get_task(t["id"])["assignee"] == "alice"
    core_services.move_task(t["id"], "todo", actor="system")
    assert core_services.get_task(t["id"])["status"] == "todo"


# ── AP-361-style replay: gate advance hand-off ────────────────────────────

def _setup_review_scenario(db_session):
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
        dod = [{"text": "done it", "checked": True}]
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


def test_gate_advance_hand_off_logs_activity_as_workflow(db_session):
    """Every state change from the automated hand-off shows up in the
    activity feed with actor='workflow' — the AP-375 criterion falling out
    of the refactor, not a per-callsite patch."""
    pid, task_id, run_id, impl_id, reviewer_id = _setup_review_scenario(db_session)
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "next123"}):
        out = workflow.advance_after_run(run_id)
    assert out["advanced"] is True
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "review"
        assert t.assignee == "senior reviewer"
        acts = db.query(Activity).filter(Activity.task_id == task_id).all()
        assert any(a.actor == "workflow" and a.action == "task.move" for a in acts)
        assert any(a.actor == "workflow" and a.action == "task.update" for a in acts)


def test_gate_advance_respects_project_gates_enabled(db_session):
    """The move now goes through TaskService.move(), which re-runs
    gates.enforce() when the project opted in — same evidence, so a
    passing workflow-side check must still pass here (no spurious
    re-entrant failure)."""
    pid, task_id, run_id, *_ = _setup_review_scenario(db_session)
    with db_session() as db:
        p = db.get(Project, pid)
        p.gates_enabled = True
        db.commit()
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "next123"}):
        out = workflow.advance_after_run(run_id)
    assert out["advanced"] is True
    assert out["to"] == "review"


# ── AP-361-style replay: rejection hand-back ──────────────────────────────

def _setup_rejection_scenario(db_session):
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
                 status_id=_status_id(db, "in_progress"),
                 priority=TaskPriority.HIGH, assignee="senior reviewer",
                 creator="system", branch="agent/x/task/y",
                 dod_items=json.dumps([{"text": "d", "checked": False}]))
        db.add(t); db.commit()
        now = datetime.now(timezone.utc)
        db.add(Run(agent_id=impl_id, task_id=t.id, project_id=pid,
                   status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                   created_at=now - timedelta(hours=2)))
        run = Run(agent_id=reviewer_id, task_id=t.id, project_id=pid,
                  status=RunStatus.COMPLETED, outcome=RunOutcome.SUCCEEDED,
                  created_at=now - timedelta(minutes=5))
        db.add(run); db.commit()
        db.add(Activity(project_id=pid, task_id=t.id, actor="senior reviewer",
                        action="task.move", detail="review → in_progress",
                        diff=json.dumps({"status": {"from": "review",
                                                    "to": "in_progress"}})))
        db.add(Activity(project_id=pid, task_id=t.id, actor="senior reviewer",
                        action="commented", detail="fix the bug"))
        db.commit()
        return pid, t.id, run.id, impl_id, reviewer_id


def test_rejection_handback_logs_activity_as_workflow(db_session):
    pid, task_id, run_id, impl_id, _ = _setup_rejection_scenario(db_session)
    with patch("backend.forge.services.schedule_task_run",
               return_value={"run_id": "fix1"}):
        out = workflow.advance_after_run(run_id)
    assert out.get("handed_back") is True
    with db_session() as db:
        t = db.get(Task, task_id)
        assert t.assignee == "implementer-1"
        acts = db.query(Activity).filter(Activity.task_id == task_id).all()
        assert any(a.actor == "workflow" and a.action == "task.update" for a in acts)


def test_rejection_handback_to_removed_member_is_rejected_not_silent(db_session):
    """AP-374: the previous_agent target is resolved straight from run
    history — if they've since been removed from the project, the
    membership check inside update_task() must reject the assignment
    (escalate) instead of silently reassigning to a non-member."""
    pid, task_id, run_id, impl_id, _ = _setup_rejection_scenario(db_session)
    with db_session() as db:
        # Simulate the implementer having been pulled off the project.
        prof = db.get(Profile, impl_id)
        prof.default_project_id = None
        db.commit()
    with patch("backend.forge.services.schedule_task_run") as mock_dispatch:
        out = workflow.advance_after_run(run_id)
    assert out["reason"] == "review_rejected"
    assert out.get("escalated") is True
    mock_dispatch.assert_not_called()
    with db_session() as db:
        t = db.get(Task, task_id)
        assert t.assignee == "senior reviewer"   # unchanged — not reassigned
        acts = db.query(Activity).filter(Activity.task_id == task_id).all()
        assert any("not a project member" in (a.detail or "")
                   or "no longer a project member" in (a.detail or "")
                   for a in acts)


# ── AP-361-style replay: integrate-complete ────────────────────────────────

def test_complete_integration_advances_even_with_gates_enabled_and_no_pr_url(db_session):
    """Re-entrancy guard: complete_integration() now calls move_task(), which
    would otherwise re-run the full review->done gate set (pr_url_set) even
    though a real merge is stronger evidence than the pr_url proxy. The
    explicit skip_gates=True escape hatch must let this succeed."""
    with db_session() as db:
        proj = core_services.create_project("P")
        pid = proj["id"]
        p = db.get(Project, pid)
        p.workflow_enabled = True
        p.gates_enabled = True
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
        task_id, run_id = t.id, run.id

    out = workflow.complete_integration(task_id=task_id, run_id=run_id,
                                        ok=True, reason="merged")
    assert out["advanced"] is True
    assert out["to"] == "done"
    with db_session() as db:
        t = db.get(Task, task_id)
        assert db.get(Status, t.status_id).name == "done"
        acts = db.query(Activity).filter(Activity.task_id == task_id).all()
        assert any(a.actor == "workflow" and a.action == "task.move" for a in acts)
