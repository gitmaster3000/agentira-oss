"""AP-308: per-run environment isolation — engine-agnostic, mocked subprocess."""

from unittest import mock

import pytest

from agentira_cli.daemon import env_isolation as ei


# ── pure helpers ────────────────────────────────────────────────────────

def test_scope_name_sanitizes():
    assert ei._scope_name("a1b2-C3.d4") == "run_a1b2_c3_d4"
    assert ei._scope_name("") == "run_"


def test_parse_env_lines_skips_junk():
    out = ei._parse_env_lines("# comment\nDB_URL=postgres://x\nbad line\nFOO = bar\n")
    assert out == {"DB_URL": "postgres://x", "FOO": "bar"}


# ── hermetic ────────────────────────────────────────────────────────────

def test_hermetic_strips_shared_urls_and_provisions_nothing():
    env, strip, ctx = ei.provision_env(mode="hermetic", run_id="r", cwd=None)
    assert env == {}
    assert "AGENTIRA_DB_URL" in strip and "AGENTIRA_APP_DB_URL" in strip
    assert ctx is None


def test_unknown_mode_fails_closed():
    with pytest.raises(ei.EnvSetupError):
        ei.provision_env(mode="bogus", run_id="r", cwd=None)


# ── per_run_db: project command, ANY engine, captured env ───────────────

def test_per_run_db_requires_a_setup_command():
    with pytest.raises(ei.EnvSetupError):
        ei.provision_env(mode="per_run_db", run_id="r", cwd="/w")  # no cmd


def test_per_run_db_runs_cmd_captures_env_and_records_teardown():
    with mock.patch.object(ei, "_run", return_value="AGENTIRA_DB_URL=mysql://h/run_abc\n") as run:
        env, strip, ctx = ei.provision_env(
            mode="per_run_db", run_id="abc", cwd="/w",
            setup_cmd="createdb-and-print", teardown_cmd="dropdb",
            db_admin_url="mysql://admin@h",
        )
    # the daemon passed the project's command + scope/admin env — no SQL of its own
    assert run.call_args.args[0] == "createdb-and-print"
    assert run.call_args.kwargs["env"]["AGENTIRA_RUN_SCOPE"] == "run_abc"
    assert run.call_args.kwargs["env"]["AGENTIRA_DB_ADMIN_URL"] == "mysql://admin@h"
    assert env == {"AGENTIRA_DB_URL": "mysql://h/run_abc"}
    assert strip == set()
    assert ctx == {"teardown_cmd": "dropdb", "cwd": "/w", "scope": "run_abc",
                   "db_admin_url": "mysql://admin@h"}


def test_per_run_db_without_teardown_has_no_ctx():
    with mock.patch.object(ei, "_run", return_value=""):
        _, _, ctx = ei.provision_env(mode="per_run_db", run_id="abc", cwd="/w",
                                     setup_cmd="x")
    assert ctx is None  # nothing to undo → nothing to reap


# ── per_run_compose: docker-compose defaults ────────────────────────────

def test_per_run_compose_uses_compose_defaults():
    with mock.patch.object(ei, "_run", return_value="API_URL=http://h:1\n") as run:
        env, _, ctx = ei.provision_env(mode="per_run_compose", run_id="abc", cwd="/w")
    assert "docker compose" in run.call_args.args[0]
    assert env == {"API_URL": "http://h:1"}
    assert ctx["teardown_cmd"] == ei._COMPOSE_DOWN
    assert ctx["scope"] == "run_abc"


# ── teardown: generic, idempotent, never raises ─────────────────────────

def test_teardown_none_and_no_cmd_are_noops():
    ei.teardown_env(None)
    ei.teardown_env({"scope": "run_x"})  # no teardown_cmd


def test_teardown_runs_command_with_scope_env():
    ctx = {"teardown_cmd": "dropdb", "cwd": "/w", "scope": "run_x", "db_admin_url": ""}
    with mock.patch("subprocess.run") as run:
        ei.teardown_env(ctx)
    assert run.call_args.args[0] == "dropdb"
    assert run.call_args.kwargs["env"]["COMPOSE_PROJECT_NAME"] == "run_x"


def test_teardown_swallows_failures():
    ctx = {"teardown_cmd": "dropdb", "scope": "run_x"}
    with mock.patch("subprocess.run", side_effect=RuntimeError("boom")):
        ei.teardown_env(ctx)  # logged, never raised
