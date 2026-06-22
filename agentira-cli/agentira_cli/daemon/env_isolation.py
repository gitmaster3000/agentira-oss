"""AP-308: per-run environment isolation.

The worktree forks a run's *source*; this module forks the *runtime
environment* its commands hit, so two concurrent runs can't collide on the
shared dev stack (the recurring org_id / "port already in use" / migration
race class). One primitive — provision before spawn, teardown on finish —
resolved by the backend and handed here as a concrete mode:

  hermetic        — nothing provisioned; instead *strip* shared service URLs
                    from the inherited env so the suite falls back to its own
                    in-memory/file DB. Zero cost.
  per_run_db      — run the PROJECT's setup command, which provisions this
                    run's own database (ANY engine — Postgres, MySQL, SQLite,
                    Mongo, …) and prints KEY=VALUE connection vars on stdout;
                    those are injected. The project's teardown command drops it.
  per_run_compose — same mechanism with docker-compose defaults: bring up an
                    isolated stack (COMPOSE_PROJECT_NAME=run_<id>, ephemeral
                    ports), capture the service URLs it emits; `compose down`
                    on teardown.

Note the deliberate abstraction: the daemon hardcodes NOTHING about a database
engine or a language. Both non-hermetic modes are the *same* mechanism — run a
command, capture its KEY=VALUE output, run a teardown command on finish — and
differ only in the defaults per_run_compose supplies. Anything engine-specific
lives in the project-declared command, never here.

Functions, not classes (per CLAUDE.md). Provision fails CLOSED — a setup
error raises EnvSetupError and the caller refuses to spawn the agent (a run
silently falling back to shared infra is exactly what we're preventing).
Teardown is idempotent and never raises into the run path; the teardown ctx
is also persisted to the inflight registry so a daemon crash can't leak a DB
or a stack (startup reap drops orphans).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess

logger = logging.getLogger("agentira.daemon.env_isolation")

# Inherited vars that point at shared services. Hermetic mode strips these so
# a run can't reach the developer's long-lived stack; the non-hermetic modes
# let the setup command emit its own replacements.
SHARED_SERVICE_VARS = {"AGENTIRA_DB_URL", "AGENTIRA_APP_DB_URL"}

# Defaults for per_run_compose only — compose IS docker, so these are
# engine-agnostic. per_run_db has NO built-in command on purpose (the project
# declares it, so any DB engine works).
_COMPOSE_UP = "docker compose -p $COMPOSE_PROJECT_NAME up -d --wait"
_COMPOSE_DOWN = "docker compose -p $COMPOSE_PROJECT_NAME down -v"

_SETUP_TIMEOUT_S = int(os.environ.get("AGENTIRA_ENV_SETUP_TIMEOUT", "300"))
_TEARDOWN_TIMEOUT_S = int(os.environ.get("AGENTIRA_ENV_TEARDOWN_TIMEOUT", "120"))


class EnvSetupError(Exception):
    """Raised when provisioning fails — the run must fail closed."""


def _scope_name(run_id: str) -> str:
    """A safe identifier for this run (compose project name, DB name, etc.).
    Exposed to commands as $AGENTIRA_RUN_SCOPE and $COMPOSE_PROJECT_NAME."""
    return "run_" + re.sub(r"[^a-z0-9]", "_", (run_id or "").lower())


def _scope_env(inherited_env: dict, scope: str, db_admin_url: str) -> dict:
    """Environment for a setup/teardown command: the inherited env plus the
    run scope and (optional) admin URL the command may need to provision."""
    env = {**os.environ, **inherited_env, "AGENTIRA_RUN_SCOPE": scope,
           "COMPOSE_PROJECT_NAME": scope}
    if db_admin_url:
        env["AGENTIRA_DB_ADMIN_URL"] = db_admin_url
    return env


def _run(cmd, *, cwd, env, timeout, what: str) -> str:
    """Run a command, returning stdout. Raise EnvSetupError on failure —
    captures stderr in the diagnostic so the run surfaces an actionable cause."""
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, env=env, timeout=timeout,
            capture_output=True, text=True, shell=True,
        )
    except subprocess.TimeoutExpired:
        raise EnvSetupError(f"{what}: timed out after {timeout}s")
    except OSError as exc:
        raise EnvSetupError(f"{what}: {exc}")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-500:]
        raise EnvSetupError(f"{what}: exit {proc.returncode}: {tail}")
    return proc.stdout or ""


def _parse_env_lines(text: str) -> dict:
    """Pull KEY=VALUE lines out of a setup command's stdout."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            out[key] = val.strip()
    return out


def provision_env(*, mode: str, run_id: str, cwd: str | None,
                  setup_cmd: str = "", teardown_cmd: str = "",
                  db_admin_url: str = "", inherited_env: dict | None = None):
    """Provision the run's isolated environment.

    Returns (provisioned_env, strip, teardown_ctx):
      provisioned_env — vars to inject into the agent subprocess.
      strip           — env var names to remove from the inherited env.
      teardown_ctx    — what teardown_env must undo (or None).

    Raises EnvSetupError on any failure (caller fails the run closed).
    """
    inherited_env = inherited_env or {}
    mode = (mode or "hermetic").strip().lower()

    if mode == "hermetic":
        return {}, set(SHARED_SERVICE_VARS), None

    if mode not in ("per_run_db", "per_run_compose"):
        raise EnvSetupError(f"unknown env_isolation mode: {mode!r}")

    # Both non-hermetic modes share ONE mechanism: run a command, capture its
    # KEY=VALUE output, remember a teardown command. per_run_compose supplies
    # docker-compose defaults; per_run_db is entirely project-declared so any
    # database engine works without engine-specific code in the daemon.
    up, down = setup_cmd, teardown_cmd
    if mode == "per_run_compose":
        up = up or _COMPOSE_UP
        down = down or _COMPOSE_DOWN
    if not up:
        raise EnvSetupError(
            "per_run_db needs env_setup_cmd — the command that provisions this "
            "run's database (any engine) and prints KEY=VALUE connection vars "
            "on stdout (e.g. createdb + echo AGENTIRA_DB_URL=...)")

    scope = _scope_name(run_id)
    run_env = _scope_env(inherited_env, scope, db_admin_url)
    out = _run(up, cwd=cwd, env=run_env, timeout=_SETUP_TIMEOUT_S,
               what=f"{mode}: setup")
    # Nothing to undo without a teardown command — no ctx, no reap entry.
    ctx = ({"teardown_cmd": down, "cwd": cwd, "scope": scope,
            "db_admin_url": db_admin_url} if down else None)
    return _parse_env_lines(out), set(), ctx


def teardown_env(teardown_ctx: dict | None) -> None:
    """Run the run's teardown command. Idempotent (the project's command must
    be), never raises into the run path — a failure is logged and left for the
    startup reaper to retry from the persisted ctx."""
    if not teardown_ctx:
        return
    cmd = teardown_ctx.get("teardown_cmd")
    if not cmd:
        return
    scope = teardown_ctx.get("scope", "")
    env = _scope_env({}, scope, teardown_ctx.get("db_admin_url", ""))
    try:
        subprocess.run(cmd, cwd=teardown_ctx.get("cwd"), env=env, shell=True,
                       capture_output=True, text=True, timeout=_TEARDOWN_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — teardown must never raise
        logger.warning("env teardown failed: %s — left for reap", exc)
