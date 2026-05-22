"""AP-123: per-run git worktrees.

Backend side of the contract:
  - prepare_task_run stamps worktree_path + worktree_branch on the row
    so the daemon knows where to materialize.
  - Each run gets its own path + branch (different runs of the same
    task collide-free).
  - complete_trigger's terminal returns carry cleanup_worktree +
    cleanup_branch so the daemon can git-worktree-remove on the way out.
  - The paused branch does NOT cleanup (resume needs the worktree).
  - The serialize-by-single-worktree guard is lifted: an agent with
    max_concurrent_runs=2 can have two RUNNING task runs at once.

The daemon-side git operations are exercised in agentira-cli/tests.
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
from backend.forge.models import ForgeRuntime, Run, RunStatus, RuntimeStatus
from backend.models import Profile


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


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
    return {"task_id": task["id"], "agent_id": agent["id"],
            "project_id": project["id"]}


# ── prepare stamps worktree fields ───────────────────────────────────

def test_prepare_stamps_worktree_path_and_branch(test_db):
    s = _setup(test_db)
    r = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    assert r["worktree_path"], "worktree_path must be set on prepare"
    assert r["worktree_branch"], "worktree_branch must be set on prepare"
    assert s["agent_id"] in r["worktree_path"]
    assert r["worktree_path"].rstrip("/").endswith(f"run-{r['id']}")
    assert r["worktree_branch"].startswith(f"agent/{s['agent_id'][:8]}/run/")
    # Path stays tilde-prefixed — backend container's ~ is /root but the
    # daemon runs on the host. The daemon expanduser's at use time.
    assert r["worktree_path"].startswith("~/.agentira/"), r["worktree_path"]


def test_two_runs_get_distinct_worktrees(test_db):
    """Re-running the same task lands a second Run row with its own
    path + branch — no collision."""
    s = _setup(test_db)
    r1 = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    r2 = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    assert r1["worktree_path"] != r2["worktree_path"]
    assert r1["worktree_branch"] != r2["worktree_branch"]


# ── complete_trigger surfaces cleanup hint ───────────────────────────

def test_terminal_complete_returns_cleanup_hint(test_db):
    """On a successful trigger-complete the daemon needs the path +
    branch to git-worktree-remove."""
    s = _setup(test_db)
    r = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    # Promote to RUNNING so complete_run won't reject.
    with forge_services._session() as db:
        db.query(Run).filter(Run.id == r["id"]).update({"status": RunStatus.RUNNING})
        db.commit()
    res = forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t", run_id=r["id"],
        success=True, input_tokens=10, output_tokens=5,
    )
    assert res.get("cleanup_worktree") == r["worktree_path"]
    assert res.get("cleanup_branch") == r["worktree_branch"]


def test_cancelled_complete_also_returns_cleanup_hint(test_db):
    s = _setup(test_db)
    r = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    with forge_services._session() as db:
        db.query(Run).filter(Run.id == r["id"]).update({"status": RunStatus.RUNNING})
        db.commit()
    res = forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t", run_id=r["id"],
        success=False, cancelled=True, error="Cancelled by user.",
    )
    assert res.get("cleanup_worktree") == r["worktree_path"]
    assert res.get("cleanup_branch") == r["worktree_branch"]


def test_paused_complete_does_NOT_cleanup(test_db):
    """PAUSED is resumable — the worktree must survive."""
    s = _setup(test_db)
    r = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    with forge_services._session() as db:
        db.query(Run).filter(Run.id == r["id"]).update({"status": RunStatus.RUNNING})
        db.commit()
    res = forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t", run_id=r["id"],
        success=False, paused=True, session_id="sess-1",
    )
    # The paused branch returns early — no cleanup keys at all.
    assert "cleanup_worktree" not in res
    assert "cleanup_branch" not in res


# ── concurrency cap ──────────────────────────────────────────────────

def test_max_concurrent_runs_2_allows_two_concurrent_dispatches(test_db):
    """The serialize-per-agent guard is lifted: with concurrency=2 the
    second dispatch must NOT be rejected by the in-flight check."""
    s = _setup(test_db)
    # Bump the agent's profile concurrency.
    with forge_services._session() as db:
        prof = db.query(Profile).filter(Profile.id == s["agent_id"]).first()
        prof.max_concurrent_runs = 2
        db.commit()

    # First task → prepare + simulate it transitioning to RUNNING.
    r1 = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    with forge_services._session() as db:
        db.query(Run).filter(Run.id == r1["id"]).update({"status": RunStatus.RUNNING})
        db.commit()

    # Second task on the same agent — should NOT be rejected (cap=2).
    project = core_services.create_project("P2", actor="system")
    t2 = core_services.create_task(project["id"], "T2", actor="system")
    r2 = forge_services.prepare_task_run(
        task_id=t2["id"], agent_id=s["agent_id"],
    )
    # Mock the daemon dispatch — we only care about the in-flight guard.
    from unittest.mock import MagicMock
    with patch("backend.forge.services._dispatch_coro",
               MagicMock(return_value=None)):
        result = forge_services.dispatch_pending_run(run_id=r2["id"])
    assert "error" not in result, result


def test_max_concurrent_runs_1_still_rejects_second(test_db):
    """The cap is real, just configurable. Default 1 still serializes."""
    s = _setup(test_db)
    r1 = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    with forge_services._session() as db:
        db.query(Run).filter(Run.id == r1["id"]).update({"status": RunStatus.RUNNING})
        db.commit()

    project = core_services.create_project("P2", actor="system")
    t2 = core_services.create_task(project["id"], "T2", actor="system")
    r2 = forge_services.prepare_task_run(
        task_id=t2["id"], agent_id=s["agent_id"],
    )
    from unittest.mock import MagicMock
    with patch("backend.forge.services._dispatch_coro",
               MagicMock(return_value=None)):
        result = forge_services.dispatch_pending_run(run_id=r2["id"])
    assert "concurrency cap" in (result.get("error") or "").lower()
