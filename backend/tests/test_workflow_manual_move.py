"""A human moving a task between columns dispatches that column's agent with
the column's workflow prompt (policy: `manual_move` + column `on_enter` in
templates/workflow/default.yaml). Agent and workflow moves never do — those
paths dispatch on their own."""

from __future__ import annotations

from unittest.mock import patch

from backend import services as core_services
from backend.forge import workflow
from backend.forge.models import Run, RunStatus
from backend.models import Task, allow_task_write
from backend.tests.test_workflow_driver import (  # noqa: F401 — fixture
    _mk_agent, _setup_review_scenario, _status_id, db_session,
)

_DISPATCH = "backend.forge.services.schedule_task_run"


def test_human_move_to_review_dispatches_reviewer_with_review_prompt(db_session, seed_admin):
    _, task_id, _, _, reviewer_id = _setup_review_scenario(db_session)
    with patch(_DISPATCH, return_value={"run_id": "r1"}) as d:
        core_services.move_task(task_id, "review", actor="admin")
    kw = d.call_args.kwargs
    assert kw["agent_id"] == reviewer_id
    assert "reviewing this task" in kw["extra_context"]
    with db_session() as db:
        assert db.get(Task, task_id).assignee == "senior reviewer"


def test_human_move_to_review_keeps_an_assigned_reviewer(db_session, seed_admin):
    _, task_id, _, _, _ = _setup_review_scenario(db_session)
    with db_session() as db:
        other = _mk_agent(db, "lead reviewer")
        with allow_task_write():
            db.get(Task, task_id).assignee = "lead reviewer"
            db.commit()
    with patch(_DISPATCH, return_value={"run_id": "r1"}) as d:
        core_services.move_task(task_id, "review", actor="admin")
    assert d.call_args.kwargs["agent_id"] == other


def test_human_move_to_in_progress_starts_the_assigned_agent(db_session, seed_admin):
    _, task_id, _, impl_id, _ = _setup_review_scenario(db_session)
    with db_session() as db:
        with allow_task_write():
            db.get(Task, task_id).status_id = _status_id(db, "todo")
            db.commit()
    with patch(_DISPATCH, return_value={"run_id": "r1"}) as d:
        core_services.move_task(task_id, "in_progress", actor="admin")
    assert d.call_args.kwargs["agent_id"] == impl_id


def test_workflow_and_agent_moves_do_not_dispatch(db_session, seed_admin):
    _, task_id, _, _, _ = _setup_review_scenario(db_session)
    with patch(_DISPATCH) as d:
        core_services.move_task(task_id, "review", actor="workflow")
        core_services.move_task(task_id, "in_progress", actor="implementer-1",
                                skip_gates=True)
    d.assert_not_called()


def test_no_dispatch_while_a_run_is_active(db_session, seed_admin):
    pid, task_id, _, impl_id, _ = _setup_review_scenario(db_session)
    with db_session() as db:
        db.add(Run(agent_id=impl_id, task_id=task_id, project_id=pid,
                   status=RunStatus.RUNNING))
        db.commit()
    with patch(_DISPATCH) as d:
        core_services.move_task(task_id, "review", actor="admin")
    d.assert_not_called()


def test_disabled_policy_or_workflow_does_not_dispatch(db_session, seed_admin):
    _, task_id, _, _, _ = _setup_review_scenario(db_session, enabled=False)
    with patch(_DISPATCH) as d:
        core_services.move_task(task_id, "review", actor="admin")
    d.assert_not_called()


def test_manual_move_policy_is_config():
    flow = workflow.system_workflow()
    assert flow.manual_move.dispatch is True
    assert flow.column("in_progress").on_enter.dispatch_assignee is True
