"""AP-113: READY pre-run checks.

Before a READY run is started, ready_checks() validates the things that
make runs fail silently — runtime, API key, MCP, environment/keys, repo,
task context — and returns a checklist for the READY screen.
"""

from __future__ import annotations

import json
import uuid

import pytest

import backend.db as bdb
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import Agent, ForgeRuntime, RuntimeStatus
from backend.models import Profile


@pytest.fixture(autouse=True)
def test_db(pg):
    yield bdb.SessionLocal


def _seed_runtime(TestSession) -> str:
    db = TestSession()
    rt = ForgeRuntime(daemon_id="d", provider="claude",
                      binary_path="/tmp/claude", status=RuntimeStatus.ONLINE)
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    return rt_id


def _prep_run(TestSession, *, description="Do the thing", repo_path=None):
    rt_id = _seed_runtime(TestSession)
    project = core_services.create_project("P", actor="system")
    if repo_path is not None:
        core_services.update_project(project["id"], repo_path=repo_path)
    task = core_services.create_task(project["id"], "T", actor="system",
                                     description=description)
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                         runtime_id=rt_id)
    prepared = forge_services.prepare_task_run(task_id=task["id"],
                                               agent_id=agent["id"])
    return prepared["id"], agent["id"]


def _check(result, key):
    return next((c for c in result["checks"] if c["key"] == key), None)


# ── basics ─────────────────────────────────────────────────────────────

def test_ready_checks_unknown_run_errors(test_db):
    assert "error" in forge_services.ready_checks(uuid.uuid4().hex[:12])


def test_healthy_run_is_ready(test_db):
    run_id, _ = _prep_run(test_db)
    result = forge_services.ready_checks(run_id)
    assert result["ready"] is True
    assert _check(result, "runtime")["status"] == "ok"
    assert result["summary"]["fail"] == 0


def test_missing_runtime_is_a_fatal_check(test_db):
    run_id, agent_id = _prep_run(test_db)
    # Strip the runtime after prepare — simulates a misconfigured agent.
    with forge_services._session() as db:
        db.query(Agent).filter(Agent.id == agent_id).update({"runtime_id": None})
        db.commit()
    result = forge_services.ready_checks(run_id)
    assert _check(result, "runtime")["status"] == "fail"
    assert result["ready"] is False


# ── task context ───────────────────────────────────────────────────────

def test_thin_task_warns_on_context(test_db):
    run_id, _ = _prep_run(test_db, description="")
    result = forge_services.ready_checks(run_id)
    assert _check(result, "context")["status"] == "warn"
    # A warning does not block readiness.
    assert result["ready"] is True


def test_described_task_passes_context(test_db):
    run_id, _ = _prep_run(test_db, description="Implement the parser.")
    assert _check(forge_services.ready_checks(run_id), "context")["status"] == "ok"


# ── repo + git credentials ─────────────────────────────────────────────

def test_project_without_repo_warns(test_db):
    run_id, _ = _prep_run(test_db, repo_path=None)
    assert _check(forge_services.ready_checks(run_id), "repo")["status"] == "warn"


def test_repo_without_git_token_warns(test_db):
    run_id, _ = _prep_run(test_db, repo_path="/tmp/some-repo")
    result = forge_services.ready_checks(run_id)
    assert _check(result, "repo")["status"] == "ok"
    assert _check(result, "git_token")["status"] == "warn"


def test_repo_with_git_token_passes(test_db):
    run_id, agent_id = _prep_run(test_db, repo_path="/tmp/some-repo")
    with forge_services._session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        prof = db.get(Profile, a.profile_id)
        prof.env_vars = json.dumps({"GH_TOKEN": "ghp_xxx"})
        db.commit()
    result = forge_services.ready_checks(run_id)
    assert _check(result, "git_token")["status"] == "ok"
    assert _check(result, "env")["detail"].count("GH_TOKEN") == 1


# ── api key ────────────────────────────────────────────────────────────

def test_missing_api_key_warns(test_db):
    run_id, agent_id = _prep_run(test_db)
    with forge_services._session() as db:
        a = db.query(Agent).filter(Agent.id == agent_id).first()
        prof = db.get(Profile, a.profile_id)
        prof.api_key = None
        db.commit()
    assert _check(forge_services.ready_checks(run_id), "api_key")["status"] == "warn"
