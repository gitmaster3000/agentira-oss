"""AP-203: the Conductor tick is assigned-only + priority-ordered, and the
planning facts carry enough for the LLM to skill-match.

Before: pick_next_unblocked FIFO-grabbed UNASSIGNED tasks (assignee == "" OR
NULL), front-running the LLM planner and ignoring priority. Now it only
dispatches tasks the planner has ASSIGNED to that exact agent, highest
priority first.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

import backend.models  # noqa: F401
import backend.forge.models  # noqa: F401
from backend.db import Base
from backend import services as core_services
from backend.forge import conductor
from backend.models import Task, TaskPriority, Profile, Role
from backend.forge.models import Agent


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.conductor.SessionLocal", TestSession):
        s = TestSession()
        core_services._seed_defaults(s)
        s.close()
        yield TestSession


def _mk_agent(db, name="builder"):
    role = db.query(Role).first()
    prof = Profile(name=name, display_name=name, password_hash="", avatar_url="",
                   webhook_url="", role_id=role.id, api_key="k_" + name,
                   conductor_enabled=True)
    db.add(prof); db.flush()
    agent = Agent(id=prof.id, profile_id=prof.id, name=name)
    db.add(agent); db.commit()
    return agent.id


def _mk_task(db, project_id, status_id, *, title, assignee="", priority=TaskPriority.MEDIUM):
    t = Task(project_id=project_id, title=title, status_id=status_id,
             priority=priority, assignee=assignee, creator="system")
    db.add(t); db.commit()
    return t.id


def _todo_id(db):
    from backend.models import Status
    return db.query(Status).filter(Status.name == "todo").first().id


def test_tick_ignores_unassigned_tasks(db_session):
    with db_session() as db:
        proj = core_services.create_project("P")
        pid = proj["id"]
        agent_id = _mk_agent(db, "builder")
        todo = _todo_id(db)
        # An UNASSIGNED critical task must NOT be auto-picked anymore.
        _mk_task(db, pid, todo, title="floating", assignee="",
                 priority=TaskPriority.CRITICAL)
        picked = conductor.pick_next_unblocked(project_id=pid, agent_id=agent_id, db=db)
        assert picked is None, "unassigned task was grabbed — planner front-run"


def test_tick_picks_assigned_highest_priority_first(db_session):
    with db_session() as db:
        proj = core_services.create_project("P")
        pid = proj["id"]
        agent_id = _mk_agent(db, "builder")
        todo = _todo_id(db)
        _mk_task(db, pid, todo, title="low one", assignee="builder",
                 priority=TaskPriority.LOW)
        _mk_task(db, pid, todo, title="high one", assignee="builder",
                 priority=TaskPriority.HIGH)
        _mk_task(db, pid, todo, title="other agent", assignee="someone-else",
                 priority=TaskPriority.CRITICAL)
        picked = conductor.pick_next_unblocked(project_id=pid, agent_id=agent_id, db=db)
        assert picked is not None and picked.title == "high one"


def test_planning_facts_include_specialty_and_description(db_session):
    with db_session() as db:
        proj = core_services.create_project("P")
        pid = proj["id"]
        # conductor-enabled agent bound to the project, with a persona.
        role = db.query(Role).first()
        prof = Profile(name="Backend Implementer", display_name="Backend Implementer",
                       password_hash="", avatar_url="", webhook_url="", role_id=role.id,
                       api_key="k_be", conductor_enabled=True, default_project_id=pid,
                       system_prompt="You are a Backend Implementer.\nBuild APIs.",
                       model="claude-sonnet-4-6")
        db.add(prof); db.flush()
        db.add(Agent(id=prof.id, profile_id=prof.id, name="Backend Implementer"))
        db.commit()
        _mk_task(db, pid, _todo_id(db), title="Login API",
                 assignee="", priority=TaskPriority.HIGH)
        # task description for the planner
        t = db.query(Task).filter(Task.title == "Login API").first()
        t.description = "JWT auth endpoint with refresh tokens"
        db.commit()

    facts = conductor.gather_planning_facts()
    a = next(x for x in facts["agents"] if x["name"] == "Backend Implementer")
    assert a["specialty"] == "You are a Backend Implementer."
    assert a["model"] == "claude-sonnet-4-6"
    tk = next(x for x in facts["unassigned_tasks"] if x["title"] == "Login API")
    assert tk["priority"] == "high"
    assert "JWT auth" in tk["description"]
