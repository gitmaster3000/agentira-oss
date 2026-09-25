"""Loop v1 C0: the workflow driver is wired again — a succeeded run advances
its task, and the daemon's merge result is applied (not ignored)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.forge import services as forge_services, workflow
from backend.rest_api import app
from backend.tests.test_blocked_run_notification import _make_run


@pytest.fixture
def test_db(pg):
    import backend.db as bdb
    yield bdb.SessionLocal


def _with_deliverable(test_db, run_id):
    """finish_run refuses an empty 'succeeded' (no diff/artifact/PR)."""
    from backend.forge.models import Run
    db = test_db()
    db.get(Run, run_id).diff_stat = " 1 file changed, 3 insertions(+)"
    db.commit()
    db.close()


def test_finish_run_succeeded_calls_driver(test_db):
    s = _make_run(test_db)
    _with_deliverable(test_db, s["run_id"])
    with patch.object(workflow, "advance_after_run", return_value={}) as adv:
        forge_services.finish_run(s["run_id"], outcome="succeeded", summary="done")
    adv.assert_called_once_with(s["run_id"])


def test_finish_run_blocked_does_not_call_driver(test_db):
    s = _make_run(test_db)
    with patch.object(workflow, "advance_after_run", return_value={}) as adv:
        forge_services.finish_run(s["run_id"], outcome="blocked", summary="stuck")
    adv.assert_not_called()


def test_integration_result_endpoint_applies(pg, seed_admin):
    _, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    verify = {"exit_code": 1, "log_tail": "E", "duration_s": 1, "timed_out": False}
    with patch.object(workflow, "complete_integration",
                      return_value={"ok": True, "advanced": False}) as ci:
        r = c.post("/api/forge/daemon/integration-result",
                   json={"daemon_id": "d", "task_id": "t1", "run_id": "r1",
                         "ok": False, "reason": "verify_failed: exit 1",
                         "verify": verify})
    assert r.status_code == 200
    ci.assert_called_once_with(task_id="t1", run_id="r1", ok=False,
                               reason="verify_failed: exit 1", verify=verify)
