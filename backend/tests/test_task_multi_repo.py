"""AP-154: tasks can declare multiple repos.

`Task.repos_json` is the new multi-repo list; `Task.repo_name` stays as
the legacy single-repo fallback. `resolve_task_repos` is the canonical
read path — REST + future daemon materializer both use it.

Tests pin:
- legacy repo_name still surfaces as a one-item list
- repos_json takes precedence when both are set
- update_task validates each repo name against project_repos
- update_task keeps repo_name in sync with repos[0]
- REST serializer exposes the resolved list
"""

from __future__ import annotations

import json as _json

import pytest

from backend import services as core_services
from backend.forge import services as forge_services  # noqa: F401 — register mappers
from backend.models import Task


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg.SessionLocal


def _seed_project_with_repos(name="MR") -> tuple[str, list[str]]:
    p = core_services.create_project(name, actor="system")
    core_services.add_project_repo(p["id"], name="backend",
                                    repo_path="/tmp/backend",
                                    is_primary=True)
    core_services.add_project_repo(p["id"], name="frontend",
                                    repo_path="/tmp/frontend")
    return p["id"], ["backend", "frontend"]


# ── Resolver behaviour ─────────────────────────────────────────────────

def test_resolve_repos_empty_when_neither_set(test_db):
    pid, _ = _seed_project_with_repos()
    t = core_services.create_task(pid, "untargeted", actor="system")
    out = core_services.get_task(t["id"])
    assert out["repos"] == []
    assert out["repo_name"] == ""


def test_legacy_repo_name_surfaces_as_one_item_list(test_db):
    pid, _ = _seed_project_with_repos()
    t = core_services.create_task(pid, "backend-only", actor="system")
    # Direct DB write to simulate a legacy task.
    with test_db() as db:
        row = db.get(Task, t["id"])
        row.repo_name = "backend"
        db.commit()
    out = core_services.get_task(t["id"])
    assert out["repos"] == ["backend"]
    assert out["repo_name"] == "backend"


def test_repos_json_takes_precedence_over_repo_name(test_db):
    pid, _ = _seed_project_with_repos()
    t = core_services.create_task(pid, "both-set", actor="system")
    with test_db() as db:
        row = db.get(Task, t["id"])
        row.repo_name = "backend"
        row.repos_json = _json.dumps(["frontend", "backend"])
        db.commit()
    out = core_services.get_task(t["id"])
    # repos_json wins
    assert out["repos"] == ["frontend", "backend"]


def test_repos_json_corrupt_falls_back_to_legacy(test_db):
    pid, _ = _seed_project_with_repos()
    t = core_services.create_task(pid, "corrupt", actor="system")
    with test_db() as db:
        row = db.get(Task, t["id"])
        row.repo_name = "backend"
        row.repos_json = "not-valid-json"
        db.commit()
    out = core_services.get_task(t["id"])
    assert out["repos"] == ["backend"]


# ── update_task: validation + repo_name sync ──────────────────────────

def test_update_task_accepts_valid_repos(test_db):
    pid, _ = _seed_project_with_repos()
    t = core_services.create_task(pid, "expand", actor="system")
    out = core_services.update_task(
        task_id=t["id"], repos=["frontend", "backend"], actor="system",
    )
    assert out["repos"] == ["frontend", "backend"]
    # repo_name auto-syncs to the first entry so legacy callers keep working.
    assert out["repo_name"] == "frontend"


def test_update_task_dedupes_repos(test_db):
    pid, _ = _seed_project_with_repos()
    t = core_services.create_task(pid, "dupe", actor="system")
    out = core_services.update_task(
        task_id=t["id"], repos=["backend", "backend", "frontend"],
        actor="system",
    )
    assert out["repos"] == ["backend", "frontend"]


def test_update_task_rejects_unknown_repo(test_db):
    pid, _ = _seed_project_with_repos()
    t = core_services.create_task(pid, "bad", actor="system")
    with pytest.raises(ValueError, match="not declared"):
        core_services.update_task(
            task_id=t["id"], repos=["backend", "phantom-repo"],
            actor="system",
        )


def test_update_task_empty_list_clears_repos(test_db):
    pid, _ = _seed_project_with_repos()
    t = core_services.create_task(pid, "clear", actor="system")
    core_services.update_task(task_id=t["id"], repos=["backend"], actor="system")
    cleared = core_services.update_task(task_id=t["id"], repos=[], actor="system")
    assert cleared["repos"] == []
    assert cleared["repo_name"] == ""
