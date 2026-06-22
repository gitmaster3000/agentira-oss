"""add_project_repo rejects a non-absolute repo_path.

A relative host path (e.g. a dropped leading slash, "Users/me/proj") can't be
resolved on the daemon host — the worktree add silently no-ops and the agent
is stranded. Reject it at registration.
"""

from __future__ import annotations

import pytest

from backend import services as core_services
from backend.forge import models as _forge_models  # noqa: F401 — register FK tables


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg.SessionLocal


def _project() -> str:
    return core_services.create_project("P", actor="system")["id"]


def test_rejects_relative_repo_path():
    pid = _project()
    res = core_services.add_project_repo(
        pid, name="frontend", repo_path="Users/me/flowty/frontend")
    assert "error" in res
    assert "absolute" in res["error"]


def test_accepts_absolute_repo_path():
    pid = _project()
    res = core_services.add_project_repo(
        pid, name="frontend", repo_path="/Users/me/flowty/frontend")
    assert "error" not in res
    assert res["repo_path"] == "/Users/me/flowty/frontend"


def test_accepts_home_anchored_repo_path():
    pid = _project()
    res = core_services.add_project_repo(
        pid, name="frontend", repo_path="~/flowty/frontend")
    assert "error" not in res
    assert res["repo_path"] == "~/flowty/frontend"


def test_url_only_repo_still_allowed():
    pid = _project()
    res = core_services.add_project_repo(
        pid, name="frontend", repo_url="https://github.com/x/y.git")
    assert "error" not in res
