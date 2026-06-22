"""AP-296: per-repo worktree freshness policy on ProjectRepo."""

from __future__ import annotations

import pytest

from backend import services as core_services


@pytest.fixture(autouse=True)
def _harness(seed_admin):
    """Shared ephemeral-Postgres harness (org-stamped via context)."""
    yield


def _project() -> str:
    return core_services.create_project("P")["id"]


def test_default_is_always_latest():
    pid = _project()
    row = core_services.add_project_repo(pid, name="backend", repo_url="u",
                                         is_primary=True)
    assert row["worktree_freshness"] == "always_latest"


def test_update_accepts_known_policy():
    pid = _project()
    core_services.add_project_repo(pid, name="backend", repo_url="u")
    row = core_services.update_project_repo(pid, "backend",
                                            worktree_freshness="pinned")
    assert row["worktree_freshness"] == "pinned"


def test_update_rejects_unknown_policy():
    pid = _project()
    core_services.add_project_repo(pid, name="backend", repo_url="u")
    row = core_services.update_project_repo(pid, "backend",
                                            worktree_freshness="whenever")
    assert "error" in row
