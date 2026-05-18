"""Tests for AP-51 dispatch bundle assembly.

schedule_task_run must:
- load the task's project repo_path + conventions_md and forward them
- load the agent's mcp_servers + run them through build_mcp_config
- generate a per-run token
- include AGENTIRA_RUN_ID / TASK_ID / PROJECT_ID / AGENT_ID / RUN_TOKEN in env_extra
- pass everything to ws_dispatch.hub.dispatch_trigger as keyword args

We patch the hub's dispatch_trigger to capture the kwargs without
actually opening a WebSocket — keeps the test pure.
"""

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime, RuntimeStatus


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def _seed_runtime(TestSession) -> str:
    """Insert a fake online runtime so agent.runtime_id passes validation."""
    db = TestSession()
    rt = ForgeRuntime(
        daemon_id="test-daemon",
        provider="claude",
        binary_path="/tmp/claude",
        status=RuntimeStatus.ONLINE,
    )
    db.add(rt)
    db.commit()
    rt_id = rt.id
    db.close()
    return rt_id


class _FakeHub:
    """Captures the kwargs schedule_task_run forwards into hub.dispatch_trigger."""

    def __init__(self):
        self.calls: list[dict] = []

    async def dispatch_trigger(self, **kwargs):
        self.calls.append(kwargs)


def _run_async(coro):
    """schedule_task_run uses asyncio.ensure_future — drain a fresh loop
    so the coroutine actually executes within the test."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _drive(fn):
    """Run fn() inside a fresh event loop so its asyncio.ensure_future
    fires get awaited before the test asserts."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = fn()
        # Pump pending tasks so ensure_future runs.
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        return result
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_dispatch_bundle_includes_project_context_and_mcp_config(test_db, tmp_path):
    """Post agent-home refactor: repo_path on the frame is the agent's
    git worktree, not the user's raw project.repo_path. Initialize a real
    repo at a tmp_path so ensure_agent_worktree succeeds, then assert the
    daemon receives a worktree path + conventions + MCP config."""
    import subprocess
    rt_id = _seed_runtime(test_db)
    # Init a real git repo at a tmp path so ensure_worktree_base accepts it
    user_repo = tmp_path / "user-repo"
    user_repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=user_repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=user_repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=user_repo, check=True)
    (user_repo / "README.md").write_text("seed")
    subprocess.run(["git", "add", "."], cwd=user_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=user_repo, check=True)

    project = core_services.create_project("Bundle Project", actor="system")
    core_services.update_project(
        project["id"],
        repo_path=str(user_repo),
        conventions_md="# Rules\nUse ruff",
    )
    task = core_services.create_task(project["id"], "Test Task", actor="system")
    agent = forge_services.create_agent(
        name="Bundle Agent", executor_type="cli", runtime_id=rt_id,
    )

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        _drive(lambda: forge_services.schedule_task_run(
            task_id=task["id"], agent_id=agent["id"],
        ))

    assert len(fake.calls) == 1, "schedule_task_run should fire exactly one trigger"
    call = fake.calls[0]

    # repo_path on the frame now points at the agent's worktree inside its
    # home dir — NOT the user's raw project path.
    assert call["repo_path"]
    assert "repos" in call["repo_path"], call["repo_path"]
    assert call["conventions_md"] == "# Rules\nUse ruff"

    # MCP config built and serialized.
    cfg = json.loads(call["mcp_config_json"])
    assert "mcpServers" in cfg
    assert "agentira" in cfg["mcpServers"]
    assert "memory" in cfg["mcpServers"]

    # Per-run env vars present and non-empty.
    env = call["env_extra"]
    for key in ("AGENTIRA_RUN_ID", "AGENTIRA_TASK_ID", "AGENTIRA_PROJECT_ID",
                "AGENTIRA_AGENT_ID", "AGENTIRA_RUN_TOKEN"):
        assert key in env, f"missing env var {key}"
        assert env[key], f"env var {key} is empty"

    assert env["AGENTIRA_TASK_ID"] == task["id"]
    assert env["AGENTIRA_PROJECT_ID"] == project["id"]
    assert env["AGENTIRA_AGENT_ID"] == agent["id"]

    # run_token rides on its own kwarg too (env_extra duplicates it for
    # the subprocess).
    assert call["run_token"] == env["AGENTIRA_RUN_TOKEN"]


def test_dispatch_bundle_handles_project_without_repo_path(test_db):
    """If repo_path/conventions_md aren't set, dispatch must still succeed
    with empty strings — the daemon falls back to its existing behavior."""
    rt_id = _seed_runtime(test_db)
    project = core_services.create_project("Bare Project", actor="system")
    task = core_services.create_task(project["id"], "Bare Task", actor="system")
    agent = forge_services.create_agent(
        name="Bare Agent", executor_type="cli", runtime_id=rt_id,
    )

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        _drive(lambda: forge_services.schedule_task_run(
            task_id=task["id"], agent_id=agent["id"],
        ))

    call = fake.calls[0]
    # No project repo → cwd defaults to agent's home dir.
    assert "agents" in call["repo_path"] or call["repo_path"] == ""
    assert call["conventions_md"] == ""
    # MCP config still built — auto servers always there.
    cfg = json.loads(call["mcp_config_json"])
    assert "agentira" in cfg["mcpServers"]


def test_dispatch_chat_trigger_sends_empty_bundle(test_db):
    """Free-floating chat (no task, no run) shouldn't crash. dispatch_trigger
    accepts the bundle as optional kwargs; chat callers don't supply them."""
    rt_id = _seed_runtime(test_db)
    agent = forge_services.create_agent(
        name="Chat Agent", executor_type="cli", runtime_id=rt_id,
    )

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        _drive(lambda: forge_services.dispatch_trigger(
            agent["id"], "hello there", kind="chat",
        ))

    call = fake.calls[0]
    assert call["repo_path"] == ""
    assert call["conventions_md"] == ""
    assert call["mcp_config_json"] == ""
    assert call["env_extra"] == {}
    assert call["run_token"] == ""


def test_run_token_is_unique_per_dispatch(test_db):
    """Each scheduled run gets its own run token + run id — per-run, not
    per-task. Uses two agents: task runs are serialized per agent (they
    share a git worktree), so one agent can't have two concurrent runs."""
    rt_id = _seed_runtime(test_db)
    project = core_services.create_project("Tok Project", actor="system")
    task = core_services.create_task(project["id"], "Tok Task", actor="system")
    agent_a = forge_services.create_agent(
        name="Tok Agent A", executor_type="cli", runtime_id=rt_id,
    )
    agent_b = forge_services.create_agent(
        name="Tok Agent B", executor_type="cli", runtime_id=rt_id,
    )

    fake = _FakeHub()
    with patch("backend.forge.ws_dispatch.hub", fake):
        _drive(lambda: forge_services.schedule_task_run(
            task_id=task["id"], agent_id=agent_a["id"],
        ))
        _drive(lambda: forge_services.schedule_task_run(
            task_id=task["id"], agent_id=agent_b["id"],
        ))

    assert len(fake.calls) == 2
    assert fake.calls[0]["run_token"] != fake.calls[1]["run_token"]
    assert fake.calls[0]["env_extra"]["AGENTIRA_RUN_ID"] != \
           fake.calls[1]["env_extra"]["AGENTIRA_RUN_ID"]
