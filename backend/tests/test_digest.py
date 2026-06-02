"""AP-84 Digest — overnight run aggregation for a project."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.digest import generate_digest, _parse_since
from backend.forge.models import Agent, Run, RunStatus, RunOutcome


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.runs.SessionLocal", TestSession), \
         patch("backend.forge.digest.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _bootstrap():
    bot = core_services.create_service_account("bot1")
    proj = core_services.create_project("P")
    from backend.models import Task, Status
    with forge_services._session() as db:
        a = Agent(id=bot["id"], profile_id=bot["id"], name="bot1",
                  executor_type="http", model="")
        db.add(a)
        status = db.query(Status).filter(Status.name == "todo").first()
        t = Task(id=uuid.uuid4().hex, project_id=proj["id"],
                 key="P-1", title="Login bug", description="",
                 status_id=status.id)
        db.add(t)
        db.commit()
        return a.id, proj["id"], t.id


def _add_run(*, agent_id, task_id, outcome: RunOutcome | None,
             status: RunStatus, finished_offset_h: int | None = -1,
             cost: float = 0.0, summary: str = "") -> str:
    now = datetime.now(timezone.utc)
    finished = (now + timedelta(hours=finished_offset_h)) if finished_offset_h is not None else None
    rid = uuid.uuid4().hex[:12]
    with forge_services._session() as db:
        db.add(Run(id=rid, agent_id=agent_id, task_id=task_id,
                   status=status, outcome=outcome,
                   finished_at=finished, cost_usd=cost,
                   summary=summary, input_tokens=100, output_tokens=200))
        db.commit()
    return rid


def test_parse_since_accepts_hours_days_and_iso():
    now = datetime.now(timezone.utc)
    h = _parse_since("24h")
    d = _parse_since("7d")
    assert (now - h).total_seconds() == pytest.approx(24 * 3600, abs=5)
    assert (now - d).total_seconds() == pytest.approx(7 * 86400, abs=5)
    iso = _parse_since("2026-05-01T00:00:00Z")
    assert iso.year == 2026


def test_digest_counts_by_outcome():
    agent_id, project_id, task_id = _bootstrap()
    _add_run(agent_id=agent_id, task_id=task_id,
             outcome=RunOutcome.SUCCEEDED, status=RunStatus.COMPLETED,
             cost=0.50, summary="Shipped fix.")
    _add_run(agent_id=agent_id, task_id=task_id,
             outcome=RunOutcome.SUCCEEDED, status=RunStatus.COMPLETED,
             cost=0.25)
    _add_run(agent_id=agent_id, task_id=task_id,
             outcome=RunOutcome.BLOCKED, status=RunStatus.COMPLETED)
    _add_run(agent_id=agent_id, task_id=task_id,
             outcome=RunOutcome.FAILED, status=RunStatus.FAILED)
    # Old run outside the window
    _add_run(agent_id=agent_id, task_id=task_id,
             outcome=RunOutcome.SUCCEEDED, status=RunStatus.COMPLETED,
             finished_offset_h=-48)

    d = generate_digest(project_id=project_id, since="24h")
    assert d["counts"]["done"] == 2
    assert d["counts"]["blocked"] == 1
    assert d["counts"]["failed"] == 1
    assert d["counts"]["total_runs"] == 4
    assert d["stats"]["cost_usd"] == pytest.approx(0.75)
    assert len(d["done"]) == 2


def test_digest_includes_in_flight_runs_regardless_of_window():
    agent_id, project_id, task_id = _bootstrap()
    # Started before the window but still RUNNING — should appear.
    _add_run(agent_id=agent_id, task_id=task_id,
             outcome=None, status=RunStatus.RUNNING,
             finished_offset_h=None)
    d = generate_digest(project_id=project_id, since="1h")
    assert d["counts"]["in_flight"] == 1


def test_digest_skips_runs_outside_project():
    agent_id, project_id, _ = _bootstrap()
    # Run with task_id NULL (free-form chat) — should not appear in project digest.
    _add_run(agent_id=agent_id, task_id=None,
             outcome=RunOutcome.SUCCEEDED, status=RunStatus.COMPLETED)
    d = generate_digest(project_id=project_id, since="24h")
    assert d["counts"]["total_runs"] == 0


def test_digest_returns_error_for_unknown_project():
    d = generate_digest(project_id="does-not-exist", since="24h")
    assert d.get("error") == "project_not_found"


def test_digest_failed_with_no_outcome_counts_as_failed():
    """AP-108-style: status=FAILED and outcome=None → a real crash."""
    agent_id, project_id, task_id = _bootstrap()
    _add_run(agent_id=agent_id, task_id=task_id,
             outcome=None, status=RunStatus.FAILED)
    d = generate_digest(project_id=project_id, since="24h")
    assert d["counts"]["failed"] == 1
