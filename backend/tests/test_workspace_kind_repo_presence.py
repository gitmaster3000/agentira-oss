"""AP-414: an attached repo makes a project a git workspace.

A project can carry a repo via `project_repos` (multi-repo model) while its
stored `workspace_kind` still says "sandbox" (the column was set before the
repo was attached, and there was no UI to change it). Sandbox blanks the
worktree fields at dispatch, so the daemon spawned the agent into an EMPTY
directory. Repo presence now wins over a stale stored "sandbox".
"""
import asyncio
from unittest.mock import patch

from sqlalchemy import text

from backend import services
from backend import db as _db
from backend.db import SessionLocal, backfill_workspace_kind
from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime, RuntimeStatus
from backend.forge.services import _resolve_workspace_kind
from backend.models import Project, ProjectRepo


def _project(pg, *, workspace_kind=None, repo_url=None, repo_path=None,
             repos=()):
    proj = services.create_project("WS " + (workspace_kind or "none"))
    pid = proj["id"]
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.workspace_kind = workspace_kind
        p.repo_url = repo_url
        p.repo_path = repo_path
        for name, url in repos:
            db.add(ProjectRepo(project_id=pid, name=name, repo_url=url))
        db.commit()
    return pid


def _resolve(pid):
    with SessionLocal() as db:
        return _resolve_workspace_kind(db.get(Project, pid))


def test_project_repo_row_overrides_stale_sandbox(pg):
    """LeadCore shape: stored sandbox, blank repo_url, one project_repos row."""
    pid = _project(pg, workspace_kind="sandbox",
                   repos=[("lead-core", "https://github.com/x/lead-core")])
    assert _resolve(pid) == "git"


def test_project_repo_row_with_blank_kind_is_git(pg):
    pid = _project(pg, repos=[("api", "https://github.com/x/api")])
    assert _resolve(pid) == "git"


def test_no_repo_stays_sandbox(pg):
    pid = _project(pg, workspace_kind="sandbox")
    assert _resolve(pid) == "sandbox"


def test_path_only_repo_row_is_local_folder(pg):
    """A repo row with no remote URL is a local folder, not a clone source."""
    proj = services.create_project("WS path only")
    pid = proj["id"]
    with SessionLocal() as db:
        db.get(Project, pid).workspace_kind = "sandbox"
        db.add(ProjectRepo(project_id=pid, name="app",
                           repo_path="/Users/x/app"))
        db.commit()
    assert _resolve(pid) == "local_folder"


def test_explicit_local_folder_survives_repo_row(pg):
    """local_folder is a deliberate choice (work off the user's own clone);
    only a stale `sandbox` is overridden."""
    pid = _project(pg, workspace_kind="local_folder", repo_path="/Users/x/app",
                   repos=[("app", "https://github.com/x/app")])
    assert _resolve(pid) == "local_folder"


class _FakeHub:
    def __init__(self):
        self.calls: list[dict] = []

    async def dispatch_trigger(self, **kwargs):
        self.calls.append(kwargs)


def _drive(fn):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = fn()
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        return result
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_dispatch_frame_provisions_a_worktree_for_a_repo_only_project(pg):
    """The LeadCore repro: repo attached via project_repos, stored kind
    'sandbox'. The frame must carry a git workspace with a clone source and a
    branch — otherwise the daemon just makedirs an empty dir and spawns."""
    with SessionLocal() as db:
        db.add(ForgeRuntime(daemon_id="d", provider="claude",
                            binary_path="/tmp/claude",
                            status=RuntimeStatus.ONLINE))
        db.commit()
        rt_id = db.query(ForgeRuntime).first().id
    proj = services.create_project("LeadCore")
    pid = proj["id"]
    with SessionLocal() as db:
        db.get(Project, pid).workspace_kind = "sandbox"
        db.add(ProjectRepo(project_id=pid, name="lead-core", is_primary=True,
                           repo_url="https://github.com/x/lead-core"))
        db.commit()
    task = services.create_task(pid, "Ship it")
    agent = forge_services.create_agent(name="A", executor_type="cli",
                                        runtime_id=rt_id)
    prepared = _drive(lambda: forge_services.prepare_task_run(
        task_id=task["id"], agent_id=agent["id"]))

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        _drive(lambda: forge_services.dispatch_pending_run(
            run_id=prepared["id"]))

    frame = fake.calls[0]
    assert frame["workspace_kind"] == "git"
    assert frame["worktree_source_url"] == "https://github.com/x/lead-core"
    assert frame["worktree_branch"]
    # agentira picks the path itself, under its own managed home.
    assert "/.agentira/agents/" in frame["repo_path"]


def test_backfill_flips_sandbox_projects_that_have_repos(pg):
    stale = _project(pg, workspace_kind="sandbox",
                     repos=[("lead-core", "https://github.com/x/lead-core")])
    keep = _project(pg, workspace_kind="sandbox")
    with _db.engine.begin() as conn:
        backfill_workspace_kind(conn)
        rows = dict(conn.execute(text(
            "SELECT id, workspace_kind FROM projects WHERE id IN (:a, :b)"),
            {"a": stale, "b": keep}).all())
    assert rows[stale] == "git"
    assert rows[keep] == "sandbox"
