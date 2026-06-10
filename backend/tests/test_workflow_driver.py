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
    fails the in_progress->review gate (when gates are enabled)."""
    pid, task_id, run_id, *_ = _setup_review_scenario(db_session, dod_checked=False)
    with db_session() as db:
        p = db.get(Project, pid)
        p.gates_enabled = True   # documents intent; gates.evaluate is direct
        db.commit()
    out = workflow.advance_after_run(run_id)
    assert out["advanced"] is False
    assert out["reason"] == "gate_failed"
    assert "dod_all_checked" in out["failures"]


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
