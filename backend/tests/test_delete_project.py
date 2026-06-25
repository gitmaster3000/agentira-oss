"""Project deletion cascades to every owned row (tasks, runs, chats, files,
repos, members) and clears the default-project pointers that would otherwise
FK-block the delete on Postgres."""
import os
import uuid

from backend.db import SessionLocal
from backend import services, attachments
from backend.models import (Project, Task, Status, Profile, ProjectRepo,
                             ProjectMember, Attachment)
from backend.forge.models import (Agent, Run, RunStatus, Conversation,
                                   AgentMessage, MessageRole, QueuedMessage)


def _seed_full_project(pg):
    """A project wired up with one of every kind of owned row + an on-disk
    attachment file. Returns (project_id, task_id, agent_id, file_path)."""
    bot = services.create_service_account("bot1")
    proj = services.create_project("Doomed")
    pid = proj["id"]
    with SessionLocal() as db:
        todo = db.query(Status).filter(Status.name == "todo").first()
        prof = db.get(Profile, bot["id"])
        prof.default_project_id = pid
        agent = Agent(id=bot["id"], profile_id=bot["id"], name="bot1",
                      executor_type="http", model="", default_project_id=pid)
        db.add(agent)
        task = Task(project_id=pid, key="D-1", title="t", description="",
                    status_id=todo.id)
        db.add(task)
        db.flush()
        tid = task.id
        db.add(ProjectMember(project_id=pid, profile_id=bot["id"]))
        db.add(Run(id=uuid.uuid4().hex[:12], agent_id=agent.id,
                   project_id=pid, status=RunStatus.COMPLETED))
        db.add(Run(id=uuid.uuid4().hex[:12], agent_id=agent.id,
                   task_id=tid, status=RunStatus.COMPLETED))
        db.add(ProjectRepo(project_id=pid, name="backend"))
        db.add(Conversation(agent_id=agent.id, scope_key=f"chat:project:{pid}"))
        db.add(Conversation(agent_id=agent.id, scope_key=f"task:{tid}"))
        db.add(AgentMessage(agent_id=agent.id, scope_key=f"chat:project:{pid}",
                            role=MessageRole.USER, content="hi"))
        db.add(QueuedMessage(agent_id=agent.id, scope_key=f"task:{tid}",
                             content="q"))
        db.commit()
        agent_id = agent.id
    # On-disk attachment file for the project.
    pdir = attachments._storage_dir(None, pid)
    os.makedirs(pdir, exist_ok=True)
    fpath = os.path.join(pdir, "note.txt")
    with open(fpath, "w") as fh:
        fh.write("data")
    with SessionLocal() as db:
        db.add(Attachment(project_id=pid, filename="note.txt", file_path=fpath,
                          content_type="text/plain", size_bytes=4))
        db.commit()
    return pid, tid, agent_id, fpath


def test_delete_project_full_cascade(pg):
    pid, tid, agent_id, fpath = _seed_full_project(pg)

    assert services.delete_project(pid) is True

    with SessionLocal() as db:
        assert db.get(Project, pid) is None
        assert db.query(Task).filter_by(project_id=pid).count() == 0
        assert db.query(ProjectMember).filter_by(project_id=pid).count() == 0
        assert db.query(ProjectRepo).filter_by(project_id=pid).count() == 0
        assert db.query(Run).filter(
            (Run.project_id == pid) | (Run.task_id == tid)).count() == 0
        assert db.query(Conversation).filter(Conversation.scope_key.in_(
            [f"chat:project:{pid}", f"task:{tid}"])).count() == 0
        assert db.query(AgentMessage).filter_by(
            scope_key=f"chat:project:{pid}").count() == 0
        assert db.query(QueuedMessage).filter_by(
            scope_key=f"task:{tid}").count() == 0
        assert db.query(Attachment).filter_by(project_id=pid).count() == 0
        # The agent and profile survive — only their default-project pointer
        # is cleared so the FK delete can proceed.
        agent = db.get(Agent, agent_id)
        assert agent is not None and agent.default_project_id is None
        assert db.get(Profile, agent_id).default_project_id is None

    # On-disk files are gone, not just the rows.
    assert not os.path.exists(fpath)


def test_delete_project_missing_returns_false(pg):
    assert services.delete_project("does-not-exist") is False
