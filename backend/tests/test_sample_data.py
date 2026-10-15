"""AP-699: realistic sample dataset for staging / PR previews."""
from __future__ import annotations

import time

import pytest
from sqlalchemy import func

from backend import attachments
from backend.db import privileged
from backend.forge.models import Run, RunStatus
from backend.models import (
    Activity, Attachment, Epic, Milestone, Notification, Org, Profile, Project,
    Task, TaskCommit, TaskDependency,
)
from backend import sample_data
from backend.sample_data import PREVIEW_ORG_ID

TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


@pytest.fixture(autouse=True)
def _tmp_attachments(tmp_path, monkeypatch):
    monkeypatch.setattr(attachments, "ATTACHMENTS_DIR", str(tmp_path))


def _tasks_by_project(pg):
    with privileged(), pg.SessionLocal() as db:
        return {
            name: n for name, n in db.query(Project.name, func.count(Task.id))
            .outerjoin(Task, Task.project_id == Project.id)
            .filter(Project.org_id == PREVIEW_ORG_ID).group_by(Project.name).all()
        }


def _row_counts(pg):
    with privileged(), pg.SessionLocal() as db:
        return {m.__tablename__: db.query(m).filter(m.org_id == PREVIEW_ORG_ID).count()
                for m in (Profile, Project, Epic, Milestone, Task, Activity,
                          Attachment, TaskCommit, TaskDependency, Notification)}


def test_seed_volumes_and_login(pg):
    t0 = time.monotonic()
    sample_data.seed()
    assert time.monotonic() - t0 < 60

    by_project = _tasks_by_project(pg)
    assert len(by_project) == 4
    assert sorted(by_project.values(), reverse=True)[:2] == [600, 120]
    assert min(by_project.values()) > 0

    with privileged(), pg.SessionLocal() as db:
        preview = db.query(Profile).filter(Profile.name == "preview").one()
        assert preview.org_id == PREVIEW_ORG_ID
        assert [r.name for r in preview.roles] == ["admin"]
        from backend.passwords import verify_password as _verify_password
        assert _verify_password("preview1234", preview.password_hash)
        humans = db.query(Profile).filter(
            Profile.org_id == PREVIEW_ORG_ID, Profile.account_type == "human").count()
        assert humans == 4
        agents = db.query(Profile).filter(
            Profile.org_id == PREVIEW_ORG_ID, Profile.account_type == "agentira_agent").count()
        assert agents >= 5
        assert db.query(Notification).filter(
            Notification.profile_id == preview.id).count() > 0
        statuses = {t.status.name for t in db.query(Task).filter(Task.org_id == PREVIEW_ORG_ID)}
        assert statuses == {"backlog", "todo", "in_progress", "review", "done"}
        long_desc = db.query(Task).filter(
            Task.org_id == PREVIEW_ORG_ID, func.length(Task.description) >= 2000).count()
        assert long_desc > 50
        assert db.query(func.max(func.length(Task.description))).scalar() <= 8000
        esg = db.query(Project).filter(Project.org_id == PREVIEW_ORG_ID,
                                       Project.name == "Easy ESG").one()
        assert db.query(Epic).filter(Epic.project_id == esg.id).count() >= 4
        assert db.query(Task).filter(Task.project_id == esg.id,
                                     Task.dod_items.isnot(None)).count() > 0
        assert db.query(Task).filter(Task.parent_id.isnot(None)).count() > 0


def test_runs_are_terminal_only(pg):
    sample_data.seed()
    with privileged(), pg.SessionLocal() as db:
        runs = db.query(Run).join(Run.task).filter(Run.task.has(org_id=PREVIEW_ORG_ID)).all()
        assert runs
        assert all(r.status in TERMINAL for r in runs)
        assert all(r.finished_at is not None for r in runs)
        from backend.forge.models import AgentMessage
        assert db.query(AgentMessage).filter(
            AgentMessage.run_id.in_([r.id for r in runs])).count() > 0


def test_seed_twice_is_idempotent(pg):
    sample_data.seed()
    first = _row_counts(pg)
    sample_data.seed()
    assert _row_counts(pg) == first


def test_reset_only_touches_preview_org(pg, seed_admin):
    # pg.org_id is a second, unrelated org with its own project + task.
    from backend import services
    proj = services.create_project("Other", "", actor="admin", members=[], initial_tasks=[])
    services.create_task(proj["id"], title="keep me", actor="admin")
    with privileged(), pg.SessionLocal() as db:
        before_other = (db.query(Task).filter(Task.org_id == pg.org_id).count(),
                        db.query(Project).filter(Project.org_id == pg.org_id).count(),
                        db.query(Profile).filter(Profile.org_id == pg.org_id).count())

    sample_data.seed()
    first = _row_counts(pg)
    with privileged(), pg.SessionLocal() as db:
        victim = db.query(Task).filter(Task.org_id == PREVIEW_ORG_ID).first()
        victim_title = victim.title
        victim.title = "EDITED BY HUMAN"
        db.commit()

    sample_data.seed(reset=True)

    assert _row_counts(pg) == first
    with privileged(), pg.SessionLocal() as db:
        assert db.query(Task).filter(Task.title == "EDITED BY HUMAN").count() == 0
        assert db.query(Task).filter(Task.title == victim_title,
                                     Task.org_id == PREVIEW_ORG_ID).count() >= 1
        after_other = (db.query(Task).filter(Task.org_id == pg.org_id).count(),
                       db.query(Project).filter(Project.org_id == pg.org_id).count(),
                       db.query(Profile).filter(Profile.org_id == pg.org_id).count())
        assert after_other == before_other
        assert db.get(Org, pg.org_id) is not None
