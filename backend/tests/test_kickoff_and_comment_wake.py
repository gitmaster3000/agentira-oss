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

from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import (
    Agent as ForgeAgent, ForgeRuntime, RuntimeStatus, AgentMessage, MessageRole,
)
from backend.models import Profile, Task, ProjectMember


@pytest.fixture(autouse=True)
def test_db(pg):
    yield


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
    """A workspace without the 'member' role can't seed the Conductor; the
    project must still be created (best-effort kickoff)."""
    # Strip member role + Conductor profile (simulating a fresh install).
    # The Conductor is an agentira_agent that needs the 'member' role; with
    # it gone, get_or_create_conductor returns an error and kickoff no-ops.
    from backend.models import Role, RolePermission
    with forge_services._session() as db:
        db.query(Profile).filter(Profile.name == "Conductor").delete()
        member = db.query(Role).filter(Role.name == "member").first()
        if member:
            (db.query(RolePermission)
               .filter(RolePermission.role_id == member.id).delete())
            db.delete(member)
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
    core_services.add_project_member(project["id"], s_name, actor="system")
    task = core_services.create_task(project["id"], "do thing", actor="system",
                                     assignee=s_name)
    # Bind a Forge agent to this profile
    with forge_services._session() as db:
        a = ForgeAgent(id=sa["id"], profile_id=sa["id"], name=s_name,
                       executor_type="cli", model="", runtime_id=rt_id)
        db.add(a); db.commit()
    return {"task_id": task["id"], "profile_name": s_name, "agent_id": sa["id"],
            "project_id": project["id"]}


def test_plain_comment_records_without_running():
    """A plain comment (no @mention) is RECORDED into the task chat as context
    but must NOT start a run (AP-184)."""
    s = _make_agent_for_task()
    from backend.forge.models import Run
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
        # The key assertion: recording a comment reserves NO run.
        assert db.query(Run).count() == 0, "a plain comment must not start a run"


def test_mention_comment_wakes_agent():
    """A comment that @mentions the agent wakes it immediately — a run is
    reserved (dispatched)."""
    s = _make_agent_for_task()
    from backend.forge.models import Run
    with patch("backend.forge.services._dispatch_coro", lambda c: None):
        core_services.add_comment(
            s["task_id"], "@backend-agent please use postgres", actor="system")
    with forge_services._session() as db:
        runs = db.query(Run).filter(Run.task_id == s["task_id"]).all()
        assert len(runs) == 1, "@mention must dispatch (reserve a run)"


def test_mention_comment_does_not_revive_parked_run():
    """A comment (even @mention) must NOT flip a parked needs_input/blocked run
    back to RUNNING. Strictly one run per (agent, task): it does NOT open a
    second run either — the comment is recorded as context (visible to the
    agent on its next turn), leaving the parked run untouched."""
    import uuid
    from backend.forge.models import Run, RunStatus, RunOutcome, AgentMessage
    s = _make_agent_for_task()  # agent name "backend-agent"
    pid = uuid.uuid4().hex[:12]
    with forge_services._session() as db:
        db.add(Run(id=pid, agent_id=s["agent_id"], task_id=s["task_id"],
                   trigger_event="task.scheduled", status=RunStatus.COMPLETED,
                   outcome=RunOutcome.NEEDS_INPUT, is_work=True))
        db.commit()
    with patch("backend.forge.services._dispatch_coro", lambda c: None):
        core_services.add_comment(s["task_id"],
                                  "@backend-agent the answer is 42", actor="system")
    with forge_services._session() as db:
        parked = db.query(Run).filter(Run.id == pid).first()
        assert parked.status == RunStatus.COMPLETED \
            and parked.outcome == RunOutcome.NEEDS_INPUT, \
            "a comment must not revive the parked run"
        runs = (db.query(Run).filter(Run.task_id == s["task_id"]).all())
        assert len(runs) == 1 and runs[0].id == pid, \
            "no second run — strictly one run per (agent, task)"
        ctx = (db.query(AgentMessage)
                 .filter(AgentMessage.agent_id == s["agent_id"],
                         AgentMessage.scope_key == f"task:{s['task_id']}").all())
        assert any("the answer is 42" in (m.content or "") for m in ctx), \
            "the comment is recorded as context for the agent's next turn"


def test_mention_comment_reuses_completed_run_no_second_run():
    """A wake into a task whose single run already COMPLETED (not parked)
    continues THAT run — one run per (agent, task), never a second."""
    import uuid
    from backend.forge.models import Run, RunStatus, RunOutcome
    s = _make_agent_for_task()  # agent name "backend-agent"
    rid = uuid.uuid4().hex[:12]
    with forge_services._session() as db:
        db.add(Run(id=rid, agent_id=s["agent_id"], task_id=s["task_id"],
                   trigger_event="task.scheduled", status=RunStatus.COMPLETED,
                   outcome=RunOutcome.SUCCEEDED, is_work=True))
        db.commit()
    with patch("backend.forge.services._dispatch_coro", lambda c: None):
        core_services.add_comment(s["task_id"],
                                  "@backend-agent one more tweak please", actor="system")
    with forge_services._session() as db:
        runs = db.query(Run).filter(Run.task_id == s["task_id"]).all()
        assert len(runs) == 1 and runs[0].id == rid, "the single run is reused"
        assert runs[0].status == RunStatus.RUNNING


def test_wake_on_comment_toggle_dispatches_plain_comment():
    """With the project toggle on, even a plain comment wakes the agent."""
    from backend.models import Project
    from backend.forge.models import Run
    s = _make_agent_for_task()
    with forge_services._session() as db:
        proj = db.query(Project).filter(Project.id == s["project_id"]).first()
        proj.wake_on_comment = True
        db.commit()
    with patch("backend.forge.services._dispatch_coro", lambda c: None):
        core_services.add_comment(s["task_id"], "just a note", actor="system")
    with forge_services._session() as db:
        runs = db.query(Run).filter(Run.task_id == s["task_id"]).all()
        assert len(runs) == 1, "toggle on → plain comment dispatches"


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
