"""AP-286: deleting a task that has a forge Run must succeed (not 500), and the
run row must be hard-deleted (runs are 1:1 with tasks). Also covers the
Task.type discriminator + the typed TaskService factory.
"""
import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend.services import bootstrap, create_project, create_task, get_task, delete_task
from backend.forge.models import Run, RunStatus  # registers forge tables on Base
from backend import tasks as task_domain
from backend.forge.repos import tasks as tasks_repo

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    with patch("backend.services.SessionLocal", TestSession):
        with patch("backend.db.engine", engine):
            bootstrap()
            yield
    Base.metadata.drop_all(bind=engine)


def _make_task_with_run(title="worked"):
    proj = create_project("Delete Cascade", actor="admin")
    task = create_task(proj["id"], title, actor="admin")
    with TestSession() as db:
        db.add(Run(agent_id="agent-x", task_id=task["id"], status=RunStatus.PENDING))
        db.commit()
    return task


@patch("backend.services.SessionLocal", TestSession)
def test_delete_task_with_run_succeeds_and_removes_run():
    task = _make_task_with_run()
    with TestSession() as db:
        assert db.query(Run).filter(Run.task_id == task["id"]).count() == 1

    assert delete_task(task["id"]) is True          # no IntegrityError / 500
    assert get_task(task["id"]) is None             # task gone

    with TestSession() as db:                        # run hard-deleted (the fix)
        assert db.query(Run).filter(Run.task_id == task["id"]).count() == 0


@patch("backend.services.SessionLocal", TestSession)
def test_delete_missing_task_returns_false():
    assert delete_task("nope-123") is False


@patch("backend.services.SessionLocal", TestSession)
def test_delete_task_removes_attachment_files(tmp_path):
    from backend.models import Attachment
    proj = create_project("Attach Cleanup", actor="admin")
    task = create_task(proj["id"], "with file", actor="admin")
    f = tmp_path / "brief.txt"
    f.write_text("hello")
    with TestSession() as db:
        db.add(Attachment(task_id=task["id"], filename="brief.txt",
                           file_path=str(f), uploaded_by="admin"))
        db.commit()

    assert f.exists()
    assert delete_task(task["id"]) is True
    assert not f.exists()  # file removed, not just the row


@patch("backend.services.SessionLocal", TestSession)
def test_repo_delete_with_children_is_idempotent_on_runs():
    task = _make_task_with_run("repo-level")
    with TestSession() as db:
        t = tasks_repo.resolve_ref(db, task["id"])
        tasks_repo.delete_with_children(db, t)
        db.commit()
        assert db.query(Run).filter(Run.task_id == task["id"]).count() == 0


@patch("backend.services.SessionLocal", TestSession)
def test_task_type_defaults_and_roundtrips():
    proj = create_project("Typed", actor="admin")
    plain = create_task(proj["id"], "plain", actor="admin")
    bug = create_task(proj["id"], "a bug", actor="admin", type="bug")
    assert plain["type"] == "task"
    assert bug["type"] == "bug"
    assert get_task(bug["id"])["type"] == "bug"


def test_resolve_factory_polymorphism():
    assert isinstance(task_domain.resolve("bug"), task_domain.TaskService)
    assert task_domain.resolve("bug").task_type == "bug"
    # unknown type falls back to the base "task" behavior, not a crash
    assert task_domain.resolve("nonsense").task_type == "task"
