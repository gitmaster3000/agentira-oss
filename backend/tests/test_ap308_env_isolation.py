"""AP-308: backend resolution of per-run environment isolation.

`_resolve_env_isolation` collapses `auto` to a concrete mode at dispatch and
packs the instruction the daemon reads off env_extra. It only uses getattr,
so a lightweight stub stands in for a Project row.
"""

from types import SimpleNamespace

from backend.forge.services import _resolve_env_isolation


def _proj(**kw):
    base = dict(env_isolation=None, env_setup_cmd=None,
                env_teardown_cmd=None, env_db_admin_url=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_auto_without_setup_cmd_is_hermetic():
    out = _resolve_env_isolation(_proj())
    assert out["AGENTIRA_ENV_ISOLATION"] == "hermetic"


def test_auto_with_setup_cmd_picks_per_run_db():
    out = _resolve_env_isolation(_proj(env_setup_cmd="createdb && echo URL=x"))
    assert out["AGENTIRA_ENV_ISOLATION"] == "per_run_db"


def test_explicit_mode_passes_through():
    out = _resolve_env_isolation(_proj(env_isolation="per_run_compose"))
    assert out["AGENTIRA_ENV_ISOLATION"] == "per_run_compose"


def test_auto_never_picks_compose():
    # even with a setup cmd, auto resolves to per_run_db, never compose.
    out = _resolve_env_isolation(_proj(env_setup_cmd="x"))
    assert out["AGENTIRA_ENV_ISOLATION"] != "per_run_compose"


def test_none_project_is_hermetic():
    out = _resolve_env_isolation(None)
    assert out["AGENTIRA_ENV_ISOLATION"] == "hermetic"


def test_override_cmds_are_packed():
    out = _resolve_env_isolation(_proj(
        env_isolation="per_run_db", env_setup_cmd="up", env_teardown_cmd="down",
        env_db_admin_url="postgres://admin",
    ))
    assert out["AGENTIRA_ENV_SETUP_CMD"] == "up"
    assert out["AGENTIRA_ENV_TEARDOWN_CMD"] == "down"
    assert out["AGENTIRA_ENV_DB_ADMIN_URL"] == "postgres://admin"
