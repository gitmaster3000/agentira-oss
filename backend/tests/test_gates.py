"""AP-158: column-exit gates on task transitions.

Pure-ish checkers (each gate reads task fields, returns ok/reason) +
the engine that runs them on a transition + the wire-up in `move_task`
that blocks the move with a structured GateFailure when the project
opted in via `gates_enabled`.
"""

from __future__ import annotations

import json as _json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services  # noqa: F401 — mappers
from backend.models import Task
from backend import gates


@pytest.fixture(autouse=True)
def test_db(pg):
    yield bdb.SessionLocal


def _seed_task(TestSession, *, dod=None, assignee="", branch="", pr_url="",
                gates_enabled=False) -> str:
    p = core_services.create_project("G", actor="system")
    if gates_enabled:
        core_services.update_project(p["id"], gates_enabled=True)
    t = core_services.create_task(
        p["id"], "T", actor="system", assignee=assignee or "",
    )
    if dod is not None or branch or pr_url:
        with TestSession() as db:
            row = db.get(Task, t["id"])
            if dod is not None:
                row.dod_items = _json.dumps(dod)
            row.branch = branch
            row.pr_url = pr_url
            db.commit()
    return t["id"]


# ── Individual gate checkers ───────────────────────────────────────────

def test_has_dod_blocks_empty_or_missing(test_db):
    t = _seed_task(test_db)
    with test_db() as db:
        row = db.get(Task, t)
        assert gates._has_dod(row).ok is False
    # Set an empty array — still fails.
    with test_db() as db:
        row = db.get(Task, t)
        row.dod_items = "[]"
        db.commit()
        assert gates._has_dod(row).ok is False


def test_has_dod_passes_with_at_least_one_item(test_db):
    t = _seed_task(test_db, dod=[{"text": "ship", "checked": False}])
    with test_db() as db:
        row = db.get(Task, t)
        assert gates._has_dod(row).ok is True


def test_has_assignee_blocks_empty(test_db):
    t = _seed_task(test_db)
    with test_db() as db:
        row = db.get(Task, t)
        assert gates._has_assignee(row).ok is False


def test_has_assignee_passes_when_set(test_db):
    t = _seed_task(test_db, assignee="Backend Implementer")
    with test_db() as db:
        row = db.get(Task, t)
        assert gates._has_assignee(row).ok is True


def test_dod_all_checked_fails_with_open_items(test_db):
    t = _seed_task(test_db, dod=[
        {"text": "tests", "checked": True},
        {"text": "docs", "checked": False},
    ])
    with test_db() as db:
        row = db.get(Task, t)
        res = gates._dod_all_checked(row)
        assert res.ok is False
        assert "docs" in res.reason


def test_dod_all_checked_passes_when_all_checked(test_db):
    t = _seed_task(test_db, dod=[
        {"text": "tests", "checked": True},
        {"text": "ship", "checked": True},
    ])
    with test_db() as db:
        row = db.get(Task, t)
        assert gates._dod_all_checked(row).ok is True


def test_has_branch_or_pr_accepts_either(test_db):
    t1 = _seed_task(test_db, branch="feat/x")
    t2 = _seed_task(test_db, pr_url="https://github.com/o/r/pull/1")
    t3 = _seed_task(test_db)
    with test_db() as db:
        assert gates._has_branch_or_pr(db.get(Task, t1)).ok is True
        assert gates._has_branch_or_pr(db.get(Task, t2)).ok is True
        assert gates._has_branch_or_pr(db.get(Task, t3)).ok is False


def test_sending_to_review_requires_a_pull_request(test_db):
    """Work is only merged through a PR, so it can't reach review without one
    — a bare branch is not enough."""
    t_branch = _seed_task(test_db, dod=[{"text": "d", "checked": True}], branch="feat/x")
    t_pr = _seed_task(test_db, dod=[{"text": "d", "checked": True}],
                      pr_url="https://github.com/o/r/pull/1")
    _attach(t_pr, "test-report")
    with test_db() as db:
        r1 = gates.evaluate(db.get(Task, t_branch), from_status="in_progress",
                            to_status="review")
        r2 = gates.evaluate(db.get(Task, t_pr), from_status="in_progress",
                            to_status="review")
    assert "pr_url_set" in {g.name for g in gates.failures(r1)}
    assert gates.failures(r2) == []


def test_pr_url_set_requires_pr(test_db):
    t1 = _seed_task(test_db, pr_url="https://github.com/o/r/pull/9")
    t2 = _seed_task(test_db, branch="feat/x")  # branch alone isn't enough
    with test_db() as db:
        assert gates._pr_url_set(db.get(Task, t1)).ok is True
        assert gates._pr_url_set(db.get(Task, t2)).ok is False


def _attach(tid, kind, name=None):
    from backend import attachments

    attachments.add(task_id=tid, filename=name or f"{kind}.md",
                    file_bytes=b"PASS", kind=kind, uploaded_by="Frontend Dev")


def _commit(tid, *, committed_at):
    core_services.link_commit(
        tid, sha=uuid.uuid4().hex[:40], message="work", branch="feat/x",
        committed_at=committed_at.isoformat(),
    )


def _proof(test_db, tid):
    with test_db() as db:
        return gates.CHECKS["proof"](db.get(Task, tid))


def test_proof_fails_without_evidence_attachment(test_db):
    tid = _seed_task(test_db)
    _attach(tid, "build")
    _attach(tid, "other")
    res = _proof(test_db, tid)
    assert res.ok is False
    assert res.name == "proof"
    assert res.reason == ("Test it yourself end to end and attach the proof "
                          "(test report or screenshot).")


@pytest.mark.parametrize("kind", ["test-report", "recording", "screenshot"])
def test_proof_accepts_each_evidence_kind(test_db, kind):
    tid = _seed_task(test_db)
    _attach(tid, kind)
    assert _proof(test_db, tid).ok is True


def test_proof_older_than_latest_commit_fails(test_db):
    tid = _seed_task(test_db)
    _attach(tid, "test-report")
    _commit(tid, committed_at=datetime.now(timezone.utc) + timedelta(hours=1))
    res = _proof(test_db, tid)
    assert res.ok is False
    assert "after your last change" in res.reason


def test_proof_newer_than_latest_commit_passes(test_db):
    tid = _seed_task(test_db)
    _commit(tid, committed_at=datetime.now(timezone.utc) - timedelta(hours=1))
    _attach(tid, "screenshot")
    assert _proof(test_db, tid).ok is True


def test_proof_uses_the_latest_of_several_commits(test_db):
    tid = _seed_task(test_db)
    _commit(tid, committed_at=datetime.now(timezone.utc) - timedelta(hours=2))
    _attach(tid, "test-report")
    _commit(tid, committed_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert _proof(test_db, tid).ok is False


# ── Engine ─────────────────────────────────────────────────────────────

def test_evaluate_returns_empty_for_unknown_transition(test_db):
    t = _seed_task(test_db)
    with test_db() as db:
        row = db.get(Task, t)
        assert gates.evaluate(row, from_status="review",
                               to_status="in_progress") == []


def test_evaluate_runs_all_gates_for_backlog_todo(test_db):
    t = _seed_task(test_db)  # no DoD, no assignee
    with test_db() as db:
        row = db.get(Task, t)
        results = gates.evaluate(row, from_status="backlog", to_status="todo")
        names = {r.name for r in results}
        assert names == {"has_dod", "has_assignee"}
        # Both fail.
        assert all(r.ok is False for r in results)


def test_enforce_raises_with_structured_failure(test_db):
    t = _seed_task(test_db)
    with test_db() as db:
        row = db.get(Task, t)
        with pytest.raises(gates.GateFailure) as exc:
            gates.enforce(row, from_status="backlog", to_status="todo")
    payload = exc.value.to_dict()
    assert payload["error"] == "transition_blocked"
    assert payload["from_status"] == "backlog"
    assert payload["to_status"] == "todo"
    failed = {g["name"] for g in payload["failed_gates"]}
    assert failed == {"has_dod", "has_assignee"}


def test_enforce_passes_when_all_gates_pass(test_db):
    t = _seed_task(test_db,
                    dod=[{"text": "ship", "checked": False}],
                    assignee="Backend Implementer")
    with test_db() as db:
        row = db.get(Task, t)
        gates.enforce(row, from_status="backlog", to_status="todo")  # no raise


# ── End-to-end: move_task respects gates_enabled ──────────────────────

def test_move_task_blocked_when_gates_enabled_and_gate_fails(test_db):
    t = _seed_task(test_db, gates_enabled=True)  # no DoD, no assignee
    with pytest.raises(gates.GateFailure):
        core_services.move_task(t, "todo", actor="system")


def test_move_task_allowed_when_gates_disabled(test_db):
    """Gates are opt-in — projects without `gates_enabled` get today's
    behavior (move passes, only RBAC is checked)."""
    t = _seed_task(test_db)  # gates_enabled=False, no DoD, no assignee
    out = core_services.move_task(t, "todo", actor="system")
    assert out["status"] == "todo"


def test_move_task_allowed_when_gates_enabled_and_all_pass(test_db):
    t = _seed_task(test_db,
                    dod=[{"text": "build", "checked": False}],
                    assignee="Backend Implementer",
                    gates_enabled=True)
    out = core_services.move_task(t, "todo", actor="system")
    assert out["status"] == "todo"


def _to_review(tid):
    core_services.move_task(tid, "todo", actor="system")
    core_services.move_task(tid, "in_progress", actor="system")
    _attach(tid, "test-report")
    core_services.move_task(tid, "review", actor="system")


def test_move_to_done_requires_pr_and_all_dod_checked(test_db):
    t = _seed_task(test_db,
                    dod=[{"text": "ship", "checked": True}],
                    assignee="A", branch="feat/x",
                    pr_url="https://github.com/o/r/pull/1",
                    gates_enabled=True)
    _to_review(t)
    with test_db() as db:
        db.get(Task, t).pr_url = ""
        db.commit()
    # Now blocked at review→done because no PR URL.
    with pytest.raises(gates.GateFailure) as exc:
        core_services.move_task(t, "done", actor="system")
    names = {g.name for g in exc.value.failed_gates}
    assert "pr_url_set" in names


def test_move_to_review_blocked_without_proof_with_plain_reason(test_db):
    tid = _seed_task(test_db, dod=[{"text": "ship", "checked": True}],
                     assignee="A", branch="feat/x", gates_enabled=True,
                     pr_url="https://github.com/o/r/pull/1")
    core_services.move_task(tid, "todo", actor="system")
    core_services.move_task(tid, "in_progress", actor="system")
    with pytest.raises(gates.GateFailure) as exc:
        core_services.move_task(tid, "review", actor="system")
    failed = exc.value.failed_gates
    assert [g.name for g in failed] == ["proof"]
    assert failed[0].reason.startswith("Test it yourself end to end")

    _attach(tid, "test-report")
    assert core_services.move_task(tid, "review", actor="system")["status"] == "review"


def test_move_to_review_blocked_when_proof_predates_last_commit(test_db):
    tid = _seed_task(test_db, dod=[{"text": "ship", "checked": True}],
                     assignee="A", branch="feat/x", gates_enabled=True,
                     pr_url="https://github.com/o/r/pull/1")
    core_services.move_task(tid, "todo", actor="system")
    core_services.move_task(tid, "in_progress", actor="system")
    _attach(tid, "test-report")
    _commit(tid, committed_at=datetime.now(timezone.utc) + timedelta(hours=1))
    with pytest.raises(gates.GateFailure) as exc:
        core_services.move_task(tid, "review", actor="system")
    assert [g.name for g in exc.value.failed_gates] == ["proof"]


def test_move_to_done_requires_proof(test_db):
    tid = _seed_task(test_db, dod=[{"text": "ship", "checked": True}],
                     assignee="A", branch="feat/x",
                     pr_url="https://github.com/o/r/pull/1", gates_enabled=True)
    _to_review(tid)
    with test_db() as db:
        for a in db.get(Task, tid).attachments:
            a.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        db.commit()
    _commit(tid, committed_at=datetime.now(timezone.utc) - timedelta(hours=1))
    with pytest.raises(gates.GateFailure) as exc:
        core_services.move_task(tid, "done", actor="system")
    assert [g.name for g in exc.value.failed_gates] == ["proof"]
    _attach(tid, "recording")
    assert core_services.move_task(tid, "done", actor="system")["status"] == "done"


# ── The workflow YAML drives the checks ────────────────────────────────

def _patched_flow(monkeypatch, checks):
    from backend.forge import workflow

    real = workflow.system_workflow()
    real.checks = checks
    monkeypatch.setattr(workflow, "system_workflow", lambda: real)


def test_default_yaml_declares_the_transition_checks():
    from backend.forge import workflow

    checks = workflow.system_workflow().checks
    assert checks["in_progress->review"] == [
        "dod_all_checked", "pr_url_set", "proof"]
    assert checks["review->done"] == ["pr_url_set", "dod_all_checked", "proof"]


def test_python_gate_table_is_gone():
    assert not hasattr(gates, "_TRANSITION_GATES")


def test_yaml_list_drives_which_checks_run(test_db, monkeypatch):
    _patched_flow(monkeypatch, {"in_progress->review": ["has_assignee"]})
    tid = _seed_task(test_db, assignee="A")
    with test_db() as db:
        results = gates.evaluate(db.get(Task, tid), from_status="in_progress",
                                 to_status="review")
    assert [r.name for r in results] == ["has_assignee"]


def test_yaml_can_drop_proof(test_db, monkeypatch):
    _patched_flow(monkeypatch, {"in_progress->review": ["has_branch_or_pr"]})
    tid = _seed_task(test_db, branch="feat/x", assignee="A", gates_enabled=True,
                     dod=[{"text": "x", "checked": True}])
    core_services.move_task(tid, "todo", actor="system")
    core_services.move_task(tid, "in_progress", actor="system")
    assert core_services.move_task(tid, "review", actor="system")["status"] == "review"


def test_unknown_check_kind_in_yaml_is_rejected():
    from backend.forge.workflow import Workflow, system_workflow

    data = system_workflow().model_dump()
    data["checks"] = {"in_progress->review": ["telepathy"]}
    with pytest.raises(ValueError, match="telepathy"):
        Workflow(**data)


def test_malformed_transition_key_is_rejected():
    from backend.forge.workflow import Workflow, system_workflow

    data = system_workflow().model_dump()
    data["checks"] = {"review-done": ["proof"]}
    with pytest.raises(ValueError, match="from->to"):
        Workflow(**data)


def test_describe_transition_reads_yaml_and_explains_proof():
    out = gates.describe_transition("in_progress", "review")
    assert [g["name"] for g in out] == [
        "dod_all_checked", "pr_url_set", "proof"]
    proof = out[-1]
    assert "test report" in proof["description"].lower()


# ── Project Settings round-trip ───────────────────────────────────────

def test_project_gates_enabled_persists_via_update_project(test_db):
    p = core_services.create_project("PG", actor="system")
    out = core_services.update_project(p["id"], gates_enabled=True)
    assert out["gates_enabled"] is True
    again = core_services.get_project(p["id"])
    assert again["gates_enabled"] is True
    cleared = core_services.update_project(p["id"], gates_enabled=False)
    assert cleared["gates_enabled"] is False
