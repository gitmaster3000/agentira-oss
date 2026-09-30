"""Hand-off to the reviewer must dispatch a real run or surface a failure."""

from __future__ import annotations

from unittest.mock import patch

from backend.forge import workflow
from backend.forge.models import Run, RunStatus
from backend.models import Activity, Notification, Task

from backend.tests.test_workflow_driver import (  # noqa: F401
    db_session as db_session, _setup_review_scenario,
)


def _reviewer_runs(db, task_id, reviewer_id):
    return (db.query(Run).filter(Run.task_id == task_id,
                                 Run.agent_id == reviewer_id).all())


def test_handoff_creates_reviewer_run_with_handoff_prompt(db_session):
    pid, task_id, run_id, impl_id, reviewer_id = _setup_review_scenario(db_session)
    frames = []
    with patch("backend.forge.services._dispatch_coro",
               side_effect=lambda c: (frames.append(c), c.close())):
        out = workflow.advance_after_run(run_id)
    assert out["advanced"] is True, out
    assert "dispatch_error" not in out, out
    assert out["run_id"]
    with db_session() as db:
        runs = _reviewer_runs(db, task_id, reviewer_id)
        assert len(runs) == 1
        assert runs[0].id == out["run_id"]
        assert runs[0].status == RunStatus.RUNNING
        assert "reviewing this task" in runs[0].initial_prompt
    assert len(frames) == 1


def test_handoff_dispatch_failure_is_surfaced(db_session):
    """Reviewer already at its concurrency cap -> dispatch refused. The task
    must say so (comment + admin notification), not stay silently unreviewed."""
    pid, task_id, run_id, impl_id, reviewer_id = _setup_review_scenario(db_session)
    with db_session() as db:
        other = Task(project_id=pid, title="other", creator="system",
                     status_id=db.get(Task, task_id).status_id)
        db.add(other)
        db.commit()
        db.add(Run(agent_id=reviewer_id, task_id=other.id, project_id=pid,
                   status=RunStatus.RUNNING))
        db.commit()
    with patch("backend.forge.services._dispatch_coro",
               side_effect=lambda c: c.close()):
        out = workflow.advance_after_run(run_id)
    assert out["advanced"] is True
    assert "concurrency cap" in out["dispatch_error"]
    with db_session() as db:
        notes = [a.detail for a in db.query(Activity)
                 .filter(Activity.task_id == task_id,
                         Activity.actor == "workflow",
                         Activity.action == "commented").all()]
        assert any("Needs attention" in n and "review" in n.lower() for n in notes), notes
        assert db.query(Notification).filter(
            Notification.type == "workflow.needs_attention").count() >= 1
        assert _reviewer_runs(db, task_id, reviewer_id) == []


def test_handoff_dispatch_exception_is_surfaced(db_session):
    pid, task_id, run_id, impl_id, reviewer_id = _setup_review_scenario(db_session)
    with patch("backend.forge.services.schedule_task_run",
               side_effect=RuntimeError("boom")):
        out = workflow.advance_after_run(run_id)
    assert out["advanced"] is True
    assert "boom" in out["dispatch_error"]
    with db_session() as db:
        notes = [a.detail for a in db.query(Activity)
                 .filter(Activity.task_id == task_id,
                         Activity.actor == "workflow").all()]
        assert any("Needs attention" in n and "boom" in n for n in notes), notes
