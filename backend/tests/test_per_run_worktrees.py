"""Task-scoped git worktrees.

Backend side of the contract:
  - prepare_task_run stamps worktree_path + worktree_branch on the row
    so the daemon knows where to materialize.
  - The path + branch are pinned to (agent, task) — every run/chat on
    the same (agent, task) shares one worktree so claude --resume keeps
    working across runs and chats.
  - ADR 009: the worktree is the conversation home and is NEVER torn
    down on a terminal run (success/cancel/pause) — it's reused by every
    run/chat in the task so working files + claude --resume survive.
    Teardown lives only in a task archive/delete hook.
  - Two RUNNING runs on the same (agent, task) are rejected (shared
    cwd would collide). Concurrent runs across DIFFERENT tasks are
    allowed up to max_concurrent_runs.

The daemon-side git operations are exercised in agentira-cli/tests.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime, Run, RunStatus, RuntimeStatus
from backend.models import Profile


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg.SessionLocal


def _setup(TestSession) -> dict:
    with bdb.SessionLocal() as db:
        rt = ForgeRuntime(daemon_id="d", provider="claude", binary_path="/tmp/c",
                          status=RuntimeStatus.ONLINE)
        db.add(rt)
        db.commit()
        rt_id = rt.id
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
    assert r["worktree_path"].rstrip("/").endswith(f"task-{s['task_id'][:8]}")
    assert r["worktree_branch"].startswith(f"agent/{s['agent_id'][:8]}/task/")
    # Tilde-prefixed; daemon expanduser's at use time (backend may be in
    # a container where ~ = /root).
    assert r["worktree_path"].startswith("~/.agentira/"), r["worktree_path"]


def test_two_runs_on_same_task_share_worktree(test_db):
    """Pinned-by-scope: the second run on the same (agent, task) lands
    in the SAME worktree + branch. claude --resume needs this."""
    s = _setup(test_db)
    r1 = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    r2 = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    assert r1["worktree_path"] == r2["worktree_path"]
    assert r1["worktree_branch"] == r2["worktree_branch"]


def test_runs_on_different_tasks_get_distinct_worktrees(test_db):
    s = _setup(test_db)
    t2 = core_services.create_task(s["project_id"], "T2", actor="system")
    r1 = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    r2 = forge_services.prepare_task_run(
        task_id=t2["id"], agent_id=s["agent_id"],
    )
    assert r1["worktree_path"] != r2["worktree_path"]
    assert r1["worktree_branch"] != r2["worktree_branch"]


# ── complete_trigger surfaces cleanup hint ───────────────────────────

def test_terminal_complete_does_NOT_cleanup(test_db):
    """ADR 009: the (agent, task) worktree is the conversation home and
    is reused by every run/chat in the task, so a terminal run must NOT
    tear it down — no cleanup hint is returned. (Was the AP-123 behavior;
    teardown now lives only in a task archive/delete hook.)"""
    s = _setup(test_db)
    r = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    with forge_services._session() as db:
        db.query(Run).filter(Run.id == r["id"]).update({"status": RunStatus.RUNNING})
        db.commit()
    res = forge_services.complete_trigger(
        agent_id=s["agent_id"], trace_id="t", run_id=r["id"],
        success=True, input_tokens=10, output_tokens=5,
    )
    assert not res.get("cleanup_worktree")
    assert not res.get("cleanup_branch")


def test_cancelled_complete_also_does_NOT_cleanup(test_db):
    """ADR 009: cancel is not the end of the task — the worktree (and the
    conversation cwd) must survive a cancelled run too."""
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
    assert not res.get("cleanup_worktree")
    assert not res.get("cleanup_branch")


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
    assert "cleanup_worktree" not in res
    assert "cleanup_branch" not in res


# ── concurrency cap ──────────────────────────────────────────────────

def test_two_concurrent_runs_on_same_task_rejected(test_db):
    """Pinned cwd ⇒ the second run on the same (agent, task) MUST be
    rejected even if max_concurrent_runs is high. Two RUNNING claudes
    in the same working tree would clobber each other."""
    s = _setup(test_db)
    with forge_services._session() as db:
        prof = db.query(Profile).filter(Profile.id == s["agent_id"]).first()
        prof.max_concurrent_runs = 5
        db.commit()

    r1 = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    with forge_services._session() as db:
        db.query(Run).filter(Run.id == r1["id"]).update({"status": RunStatus.RUNNING})
        db.commit()

    # AP-298: one run per (agent, task). Preparing again returns the SAME live
    # run rather than minting a second — two concurrent runs on one task are
    # impossible by construction.
    r2 = forge_services.prepare_task_run(
        task_id=s["task_id"], agent_id=s["agent_id"],
    )
    assert r2["id"] == r1["id"], r2
    # And the already-running run can't be re-dispatched into a second claude.
    from unittest.mock import MagicMock
    with patch("backend.forge.services._dispatch_coro",
               MagicMock(return_value=None)):
        result = forge_services.dispatch_pending_run(run_id=r2["id"])
    assert "running" in (result.get("error") or "").lower(), result


def test_max_concurrent_runs_2_allows_two_different_tasks(test_db):
    """Cross-task concurrency is allowed up to max_concurrent_runs."""
    s = _setup(test_db)
    with forge_services._session() as db:
        prof = db.query(Profile).filter(Profile.id == s["agent_id"]).first()
        prof.max_concurrent_runs = 2
        db.commit()

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
    assert "error" not in result, result


def test_max_concurrent_runs_1_rejects_second_across_tasks(test_db):
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
