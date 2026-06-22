"""finish_run rejects outcome="succeeded" when there's no deliverable.

An agent declaring succeeded with no diff + no artifacts + no PR is the
hallucinated-completion failure mode: the Run page renders as ✅ but the
human opens it and finds nothing. Reject up front so the agent corrects
course (commit, register artifact, or declare blocked).
"""

from __future__ import annotations

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime, Run, RuntimeStatus


@pytest.fixture(autouse=True)
def test_db(pg):
    yield bdb.SessionLocal


def _setup(TestSession) -> dict:
    db = TestSession()
    rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                      status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    project = core_services.create_project("P", actor="system")
    task = core_services.create_task(project["id"], "T", actor="system")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    run = forge_services.create_run(
        agent_id=agent["id"], task_id=task["id"], project_id=project["id"],
    )
    return {"run_id": run["id"], "agent_id": agent["id"],
            "task_id": task["id"]}


# ── reject ───────────────────────────────────────────────────────────

def test_succeeded_with_no_output_is_rejected(test_db):
    """Diff empty + artifacts empty + task has no PR → reject."""
    s = _setup(test_db)
    res = forge_services.finish_run(s["run_id"], outcome="succeeded",
                                    summary="I did the thing")
    assert res["ok"] is False
    assert "deliverable" in res["error"].lower()
    assert res["missing"] == {"diff": True, "artifacts": True, "pr": True}
    # And the row stays as-is (outcome unset).
    r = forge_services.get_run(s["run_id"])
    assert r["outcome"] is None


def test_succeeded_summary_alone_is_not_enough(test_db):
    """A pretty summary doesn't count — needs an actual deliverable."""
    s = _setup(test_db)
    res = forge_services.finish_run(
        s["run_id"], outcome="succeeded",
        summary="Refactored 14 modules, added 800 tests, deployed to prod",
    )
    assert res["ok"] is False


# ── accept when there's real output ──────────────────────────────────

def test_succeeded_with_diff_is_accepted(test_db):
    """Even one line of diff is enough — the human has something to read."""
    s = _setup(test_db)
    with forge_services._session() as db:
        r = db.query(Run).filter(Run.id == s["run_id"]).first()
        r.diff_stat = " 1 file changed, 1 insertion(+)"
        db.commit()
    res = forge_services.finish_run(s["run_id"], outcome="succeeded",
                                    summary="added a print statement")
    assert res["ok"] is True
    assert forge_services.get_run(s["run_id"])["outcome"] == "succeeded"


def test_succeeded_with_artifact_is_accepted(test_db):
    """A registered artifact unblocks the success declaration."""
    s = _setup(test_db)
    forge_services.register_run_artifact(
        run_id=s["run_id"], url="https://github.com/x/y/pull/42",
        label="PR #42", kind="pr",
    )
    res = forge_services.finish_run(s["run_id"], outcome="succeeded",
                                    summary="opened PR")
    assert res["ok"] is True


def test_succeeded_with_task_pr_url_is_accepted(test_db):
    """If the agent set task.pr_url via update_task, the Run page shows
    the link via the task — that counts as a deliverable too."""
    s = _setup(test_db)
    from backend.models import Task
    with forge_services._session() as db:
        t = db.query(Task).filter(Task.id == s["task_id"]).first()
        t.pr_url = "https://github.com/x/y/pull/42"
        db.commit()
    res = forge_services.finish_run(s["run_id"], outcome="succeeded",
                                    summary="opened PR")
    assert res["ok"] is True


# ── non-succeeded outcomes are NEVER rejected ────────────────────────

def test_blocked_is_always_accepted(test_db):
    """An agent declaring blocked is the desired fallback when there's
    no deliverable — it must NEVER be rejected by the guard."""
    s = _setup(test_db)
    res = forge_services.finish_run(s["run_id"], outcome="blocked",
                                    summary="need GH_TOKEN")
    assert res["ok"] is True
    assert forge_services.get_run(s["run_id"])["outcome"] == "blocked"


def test_failed_with_no_output_is_accepted(test_db):
    """The guard targets the hallucinated-success case only. Failed +
    no output is a legitimate, unsurprising state."""
    s = _setup(test_db)
    res = forge_services.finish_run(s["run_id"], outcome="failed",
                                    summary="ran out of context")
    assert res["ok"] is True


def test_needs_input_with_no_output_is_accepted(test_db):
    s = _setup(test_db)
    res = forge_services.finish_run(s["run_id"], outcome="needs_input",
                                    summary="which env?")
    assert res["ok"] is True
