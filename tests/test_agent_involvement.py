"""Tests for AP-77 get_agent_involvement aggregator.

Backs the get_my_involvement MCP tool. Must:
- Aggregate forge_runs per project with run_count, last_active, tasks_touched.
- Sum tokens + cost across all runs of the agent.
- Skip runs without project association (free-form chat).
- Scope strictly by agent_id — no cross-agent leakage.
- Return a stable empty-state for an agent with no runs.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import Agent, Run, RunStatus
from backend.models import Project, Task


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    # expire_on_commit=False so tests that read attrs after commit/close
    # don't trip DetachedInstanceError. Production session uses default.
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.runs.SessionLocal", TestSession):
        # Seed the default test profile / workspace so projects can be created.
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _mk_agent(session, name="agent1"):
    a = Agent(id=name[:12].ljust(12, "0"), name=name)
    session.add(a)
    session.flush()
    return a


def _mk_project(session, name="P", repo_path=""):
    p = Project(id=name[:12].ljust(12, "0"), name=name, repo_path=repo_path)
    session.add(p)
    session.flush()
    return p


def _mk_task(session, project_id, title="t"):
    # Status moved from string column to status_id FK at some point;
    # look up the seeded "backlog" status.
    from backend.models import Status
    backlog = session.query(Status).filter(Status.name == "backlog").first()
    t = Task(id=(project_id + title)[:12].ljust(12, "0"),
             title=title, project_id=project_id, status_id=backlog.id)
    session.add(t)
    session.flush()
    return t


def _mk_run(session, agent_id, *, project_id=None, task_id=None,
            tokens_in=0, tokens_out=0, cost=0.0, at=None):
    r = Run(
        agent_id=agent_id,
        project_id=project_id,
        task_id=task_id,
        status=RunStatus.COMPLETED,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        cost_usd=cost,
        created_at=at or datetime.now(timezone.utc),
    )
    session.add(r)
    session.flush()
    return r


def test_no_runs_returns_empty_shape(test_db):
    db = test_db()
    a = _mk_agent(db)
    agent_id = a.id  # capture before commit/close (post-close attr access
                     # raises DetachedInstanceError as columns expire)
    db.commit()
    db.close()

    result = forge_services.get_agent_involvement(agent_id)
    assert result["agent_id"] == agent_id
    assert result["total_runs"] == 0
    assert result["projects"] == []
    assert result["total_cost_usd"] == 0.0


def test_aggregates_runs_by_project(test_db):
    db = test_db()
    a = _mk_agent(db)
    p1 = _mk_project(db, "Proj1")
    p2 = _mk_project(db, "Proj2")
    t1 = _mk_task(db, p1.id, "task-A")
    t2 = _mk_task(db, p2.id, "task-B")
    _mk_run(db, a.id, project_id=p1.id, task_id=t1.id, tokens_in=10, tokens_out=20, cost=0.5)
    _mk_run(db, a.id, project_id=p1.id, task_id=t1.id, tokens_in=5, tokens_out=10, cost=0.25)
    _mk_run(db, a.id, project_id=p2.id, task_id=t2.id, tokens_in=1, tokens_out=2, cost=0.1)
    db.commit()
    db.close()

    result = forge_services.get_agent_involvement(a.id)
    assert result["total_runs"] == 3
    assert result["total_input_tokens"] == 16
    assert result["total_output_tokens"] == 32
    assert result["total_cost_usd"] == pytest.approx(0.85)
    assert len(result["projects"]) == 2

    by_name = {p["project_name"]: p for p in result["projects"]}
    assert by_name["Proj1"]["run_count"] == 2
    assert by_name["Proj2"]["run_count"] == 1
    assert by_name["Proj1"]["tasks_touched"][0]["task_title"] == "task-A"


def test_skips_runs_without_project(test_db):
    """Free-form chat runs without project_id should not appear in
    the per-project rollup (but their tokens DO count toward totals
    so the agent's overall cost is honest)."""
    db = test_db()
    a = _mk_agent(db)
    _mk_run(db, a.id, project_id=None, tokens_in=100, tokens_out=50, cost=1.0)
    db.commit()
    db.close()

    result = forge_services.get_agent_involvement(a.id)
    assert result["total_runs"] == 1
    assert result["projects"] == []
    assert result["total_input_tokens"] == 100  # totals still include it


def test_scopes_by_agent_id_no_leakage(test_db):
    db = test_db()
    a1 = _mk_agent(db, "agent1")
    a2 = _mk_agent(db, "agent2")
    p = _mk_project(db, "Shared")
    t = _mk_task(db, p.id, "shared-task")
    _mk_run(db, a1.id, project_id=p.id, task_id=t.id, tokens_in=10)
    _mk_run(db, a2.id, project_id=p.id, task_id=t.id, tokens_in=99)
    db.commit()
    db.close()

    r1 = forge_services.get_agent_involvement(a1.id)
    r2 = forge_services.get_agent_involvement(a2.id)
    assert r1["total_runs"] == 1 and r1["total_input_tokens"] == 10
    assert r2["total_runs"] == 1 and r2["total_input_tokens"] == 99


def test_resolves_project_via_task_when_run_project_missing(test_db):
    """Run.project_id may be null on older rows; the task's project should
    still pull the run into the right bucket."""
    db = test_db()
    a = _mk_agent(db)
    p = _mk_project(db, "ViaTask")
    t = _mk_task(db, p.id, "tt")
    _mk_run(db, a.id, project_id=None, task_id=t.id, tokens_in=1)
    db.commit()
    db.close()

    result = forge_services.get_agent_involvement(a.id)
    assert len(result["projects"]) == 1
    assert result["projects"][0]["project_name"] == "ViaTask"


def test_projects_sorted_by_last_active_desc(test_db):
    db = test_db()
    a = _mk_agent(db)
    old_p = _mk_project(db, "Old")
    new_p = _mk_project(db, "New")
    old_t = _mk_task(db, old_p.id, "ot")
    new_t = _mk_task(db, new_p.id, "nt")
    now = datetime.now(timezone.utc)
    _mk_run(db, a.id, project_id=old_p.id, task_id=old_t.id,
            at=now - timedelta(days=5))
    _mk_run(db, a.id, project_id=new_p.id, task_id=new_t.id, at=now)
    db.commit()
    db.close()

    result = forge_services.get_agent_involvement(a.id)
    assert [p["project_name"] for p in result["projects"]] == ["New", "Old"]
