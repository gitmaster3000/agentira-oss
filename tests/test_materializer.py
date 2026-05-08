"""Tests for the daemon-side run-context materializer (AP-52, Phase D).

Skipped when agentira-cli isn't installed (CI's unit-tests job, where
only the backend package is available). Runs locally where the daemon
package is editable-installed.
"""

import os
from pathlib import Path

import pytest

agentira_cli_materializer = pytest.importorskip(
    "agentira_cli.daemon.materializer",
    reason="agentira-cli package not installed",
)
materialize = agentira_cli_materializer.materialize
compose_system_prompt = agentira_cli_materializer.compose_system_prompt
ensure_memory_dirs = agentira_cli_materializer.ensure_memory_dirs
SYSTEM_PROMPT_ADDENDUM = agentira_cli_materializer.SYSTEM_PROMPT_ADDENDUM
MEMORY_ADDENDUM = agentira_cli_materializer.MEMORY_ADDENDUM


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    """Point ~/.agentira at a tmp dir so workdirs land somewhere harmless."""
    monkeypatch.setattr(
        "agentira_cli.state.paths.HOME", tmp_path / ".agentira"
    )
    monkeypatch.setattr(
        "agentira_cli.state.paths.WORKSPACES_DIR",
        tmp_path / ".agentira" / "workspaces",
    )
    # workdir.task_workdir reads WORKSPACES_DIR at call time via import,
    # so reload the module so it picks up the patched constant.
    import importlib, agentira_cli.daemon.workdir as wd
    importlib.reload(wd)
    monkeypatch.setattr(
        "agentira_cli.daemon.materializer.task_workdir", wd.task_workdir
    )
    return tmp_path


def test_materialize_writes_conventions_to_workdir_when_no_repo(isolated_home):
    cwd, _ = materialize(
        workspace_id="agentA", task_id="task1",
        repo_path="", conventions_md="# Be brief",
    )
    conv = cwd / ".agentira" / "CONVENTIONS.md"
    assert conv.exists()
    assert conv.read_text() == "# Be brief"


def test_materialize_uses_repo_path_when_set(isolated_home, tmp_path):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    cwd, _ = materialize(
        workspace_id="agentA", task_id="task1",
        repo_path=str(repo), conventions_md="rules",
    )
    assert cwd == repo.resolve()
    assert (repo / ".agentira" / "CONVENTIONS.md").read_text() == "rules"


def test_materialize_falls_back_when_repo_path_missing(isolated_home):
    cwd, _ = materialize(
        workspace_id="agentA", task_id="task1",
        repo_path="/nonexistent/path/xyz",
        conventions_md="rules",
    )
    # Falls back to scratch workdir, doesn't crash.
    assert cwd.exists()
    assert cwd != Path("/nonexistent/path/xyz")


def test_courtesy_symlinks_created(isolated_home, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    cwd, _ = materialize(
        workspace_id="a", task_id="t",
        repo_path=str(repo), conventions_md="rules",
    )
    for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        link = cwd / name
        assert link.is_symlink(), f"{name} should be a symlink"


def test_courtesy_symlinks_skip_existing_files(isolated_home, tmp_path):
    """If AGENTS.md already exists in the repo, don't overwrite team intent."""
    repo = tmp_path / "repo"
    repo.mkdir()
    pre_existing = repo / "AGENTS.md"
    pre_existing.write_text("team's own AGENTS.md content")

    materialize(
        workspace_id="a", task_id="t",
        repo_path=str(repo), conventions_md="rules",
    )
    # AGENTS.md untouched; CLAUDE.md / GEMINI.md still get the symlink.
    assert pre_existing.read_text() == "team's own AGENTS.md content"
    assert not pre_existing.is_symlink()
    assert (repo / "CLAUDE.md").is_symlink()


def test_materialize_skips_conventions_when_empty(isolated_home, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    materialize(
        workspace_id="a", task_id="t",
        repo_path=str(repo), conventions_md="",
    )
    assert not (repo / ".agentira" / "CONVENTIONS.md").exists()
    # No courtesy symlinks either when there's nothing to point at.
    assert not (repo / "AGENTS.md").exists()


def test_materialize_is_idempotent(isolated_home, tmp_path):
    """Re-running materialize doesn't churn files or fail on existing symlinks."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for _ in range(3):
        materialize(
            workspace_id="a", task_id="t",
            repo_path=str(repo), conventions_md="v1",
        )
    assert (repo / ".agentira" / "CONVENTIONS.md").read_text() == "v1"
    assert (repo / "AGENTS.md").is_symlink()


def test_compose_system_prompt_with_conventions():
    out = compose_system_prompt("You are a careful agent.",
                                have_conventions=True)
    assert SYSTEM_PROMPT_ADDENDUM in out
    assert "You are a careful agent." in out
    # Addendum must come first so the model sees it before persona drift.
    assert out.index(SYSTEM_PROMPT_ADDENDUM) < out.index("You are a careful agent.")


def test_compose_system_prompt_no_conventions_skips_addendum():
    out = compose_system_prompt("You are X.", have_conventions=False)
    assert SYSTEM_PROMPT_ADDENDUM not in out
    assert out == "You are X."


def test_compose_system_prompt_empty_persona_with_conventions():
    out = compose_system_prompt("", have_conventions=True)
    assert out == SYSTEM_PROMPT_ADDENDUM


# ── Memory addendum + dir prep (AP-55) ────────────────────────────────

def test_compose_system_prompt_includes_memory_addendum_when_have_memory():
    out = compose_system_prompt(
        "You are X.", have_conventions=True, have_memory=True,
    )
    assert MEMORY_ADDENDUM in out
    assert SYSTEM_PROMPT_ADDENDUM in out
    assert "You are X." in out


def test_compose_system_prompt_omits_memory_when_not_configured():
    out = compose_system_prompt(
        "You are X.", have_conventions=True, have_memory=False,
    )
    assert MEMORY_ADDENDUM not in out


def test_compose_system_prompt_memory_only():
    """If conventions weren't materialized but memory is on, only memory
    addendum should ride. No half-empty pointers."""
    out = compose_system_prompt(
        "", have_conventions=False, have_memory=True,
    )
    assert MEMORY_ADDENDUM in out
    assert SYSTEM_PROMPT_ADDENDUM not in out


def test_ensure_memory_dirs_creates_parent(tmp_path):
    target = tmp_path / "agentX" / "projY" / "memory.json"
    cfg = (
        '{"mcpServers": {"memory": {"command": "npx", '
        '"env": {"MEMORY_FILE_PATH": "' + str(target) + '"}}}}'
    )
    assert not target.parent.exists()
    ensure_memory_dirs(cfg)
    assert target.parent.exists()
    # File itself is NOT pre-created — the memory MCP server writes it
    # on first call. We only ensure the directory.
    assert not target.exists()


def test_ensure_memory_dirs_handles_missing_env_block(tmp_path):
    """A server without env shouldn't crash — same for missing memory entry."""
    cfg = '{"mcpServers": {"agentira": {"type": "http", "url": "x"}}}'
    ensure_memory_dirs(cfg)  # must not raise


def test_ensure_memory_dirs_handles_malformed_json():
    ensure_memory_dirs("not json at all")  # silently no-op


def test_ensure_memory_dirs_handles_empty_string():
    ensure_memory_dirs("")  # silently no-op


def test_ensure_memory_dirs_idempotent(tmp_path):
    target = tmp_path / "a" / "b" / "memory.json"
    cfg = (
        '{"mcpServers": {"memory": {"command": "npx", '
        '"env": {"MEMORY_FILE_PATH": "' + str(target) + '"}}}}'
    )
    ensure_memory_dirs(cfg)
    ensure_memory_dirs(cfg)  # second call must be a no-op, not raise
    assert target.parent.exists()
