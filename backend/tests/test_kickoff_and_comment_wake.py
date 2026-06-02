"""Project kickoff + comment wake-on-agent (the "start the first project"
slice).

- A new project auto-adds the Conductor as a member and creates a
  "Plan this project" kickoff task assigned to it (status=todo).
- A comment on a task with an assigned agent dispatches the agent via
  ADR 009 D routing (send_runtime_message), so the comment shows up in
  the task chat AND wakes the agent. A comment by the agent itself does
  NOT re-dispatch (loop guard).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    Agent as ForgeAgent, ForgeRuntime, RuntimeStatus, AgentMessage, MessageRole,
)
from backend.models import Profile, Task, ProjectMember


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.conductor.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


# ── Kickoff on project create ────────────────────────────────────────────

def test_create_project_auto_adds_conductor_and_kickoff_task():
    p = core_services.create_project("My new product", actor="system")

    # Conductor is a project member
    with forge_services._session() as db:
        cond_prof = db.query(Profile).filter(Profile.name == "Conductor").first()
        assert cond_prof is not None, "Conductor profile should be seeded"
        member = (db.query(ProjectMember)
                    .filter_by(project_id=p["id"], profile_id=cond_prof.id)
                    .first())
        assert member is not None, "Conductor should be auto-added"

        # Exactly one kickoff task; assigned to Conductor; status todo
        tasks = db.query(Task).filter_by(project_id=p["id"]).all()
        assert len(tasks) == 1
        t = tasks[0]
        assert t.title == "Plan this project"
        assert t.assignee == "Conductor"
        # Prompt-as-config: the task body is owned by the user, not by
        # services.py. The Conductor's UI-editable system prompt drives
        # behavior; the body starts empty and the user fills it (or, in
        # the future, the project-creation wizard does on the user's
        # behalf — AP-153).
        assert t.description == ""


def test_kickoff_skipped_gracefully_when_bot_role_missing(test_db):
    """A workspace without the 'bot' role can't seed the Conductor; the
    project must still be created (best-effort kickoff)."""
    # Strip bot role + Conductor profile (simulating a fresh install)
    from backend.models import Role
    with forge_services._session() as db:
        db.query(Profile).filter(Profile.name == "Conductor").delete()
        db.query(Role).filter(Role.name == "bot").delete()
        db.commit()

    p = core_services.create_project("Lone project", actor="system")
    assert p and p.get("id"), "project must still be created"
    with forge_services._session() as db:
        tasks = db.query(Task).filter_by(project_id=p["id"]).all()
        # No kickoff task created (Conductor unavailable)
        assert tasks == []


# ── Comment wakes the assigned agent ─────────────────────────────────────

def _make_agent_for_task(s_name="backend-agent"):
    """An agent with a Forge runtime so it's wake-able."""
    db_engine = forge_services._session().get_bind()
    with forge_services._session() as db:
        rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                          status=RuntimeStatus.ONLINE)
        db.add(rt); db.commit(); rt_id = rt.id

    sa = core_services.create_service_account(s_name)
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "do thing", actor="system",
                                     assignee=s_name)
    # Bind a Forge agent to this profile
    with forge_services._session() as db:
        a = ForgeAgent(id=sa["id"], profile_id=sa["id"], name=s_name,
                       executor_type="cli", model="", runtime_id=rt_id)
        db.add(a); db.commit()
    return {"task_id": task["id"], "profile_name": s_name, "agent_id": sa["id"],
            "project_id": project["id"]}


def test_comment_dispatches_assigned_agent_into_task_scope():
    """A human comment on a task with an assigned agent wakes the agent
    via send_runtime_message into task:<task_id> — comment lands as a
    USER message in the chat thread."""
    s = _make_agent_for_task()
    with patch("backend.forge.services._dispatch_coro", lambda c: None):
        core_services.add_comment(s["task_id"], "please use postgres", actor="system")

    with forge_services._session() as db:
        msgs = (db.query(AgentMessage)
                  .filter(AgentMessage.scope_key == f"task:{s['task_id']}")
                  .all())
        assert len(msgs) == 1
        assert msgs[0].role == MessageRole.USER
        assert "please use postgres" in msgs[0].content
        assert "Comment from system" in msgs[0].content


def test_comment_from_assigned_agent_does_not_loop():
    """An agent's own comment on its own assigned task must NOT re-
    dispatch itself."""
    s = _make_agent_for_task()
    with patch("backend.forge.services._dispatch_coro", lambda c: None):
        core_services.add_comment(s["task_id"], "I'll start now",
                                  actor=s["profile_name"])
    with forge_services._session() as db:
        msgs = (db.query(AgentMessage)
                  .filter(AgentMessage.scope_key == f"task:{s['task_id']}")
                  .all())
        assert msgs == [], "self-comment must not dispatch"


def test_comment_on_unassigned_task_is_a_no_op_for_dispatch():
    """No assignee -> no agent to wake; the comment still records."""
    project = core_services.create_project("Q", actor="system")
    task = core_services.create_task(project["id"], "free task", actor="system")
    with patch("backend.forge.services._dispatch_coro", lambda c: None):
        core_services.add_comment(task["id"], "hello", actor="system")
    with forge_services._session() as db:
        msgs = (db.query(AgentMessage)
                  .filter(AgentMessage.scope_key == f"task:{task['id']}")
                  .all())
        assert msgs == []
