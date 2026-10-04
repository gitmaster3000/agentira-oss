"""Regression coverage for the structured-review MCP service."""

from __future__ import annotations

import json

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime, RuntimeStatus
from backend.models import Activity


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg.SessionLocal


def _review_run() -> tuple[str, str]:
    with bdb.SessionLocal() as db:
        runtime = ForgeRuntime(
            daemon_id="review-daemon",
            provider="claude",
            binary_path="/tmp/claude",
            status=RuntimeStatus.ONLINE,
        )
        db.add(runtime)
        db.commit()
        runtime_id = runtime.id

    project = core_services.create_project("Review project", actor="system")
    task = core_services.create_task(
        project["id"], "Review this change", actor="system"
    )
    agent = forge_services.create_agent(
        name="Reviewer", executor_type="cli", runtime_id=runtime_id
    )
    run = forge_services.create_run(
        agent_id=agent["id"], task_id=task["id"], project_id=project["id"]
    )
    return run["id"], task["id"]


def test_submit_review_returns_task_id_and_retry_is_idempotent(test_db):
    run_id, task_id = _review_run()

    first = forge_services.submit_review(
        run_id, approve=True, actor="system", note="Correct and complete"
    )
    retry = forge_services.submit_review(
        run_id, approve=True, actor="system", note="Retry after transport error"
    )

    assert first == {"ok": True, "verdict": "approve", "task_id": task_id}
    assert retry == first

    with bdb.SessionLocal() as db:
        rows = (
            db.query(Activity)
            .filter(
                Activity.task_id == task_id,
                Activity.actor == "system",
                Activity.action == "review_verdict",
            )
            .all()
        )
    assert len(rows) == 1
    assert json.loads(rows[0].diff) == {
        "run_id": run_id,
        "verdict": "approve",
    }
