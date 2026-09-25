"""Database engine and session management.

Multi-tenancy (org isolation) is enforced at two layers:

1. **Postgres RLS** (the real guarantee). Request-path sessions connect as a
   non-superuser role (`agentira_app`) and run `SET LOCAL app.org = <org_id>`
   at transaction start; RLS policies on every org-scoped table filter to that
   org. Even a forgotten WHERE clause can't leak across orgs.
2. **App-layer belt** (dev parity / defence-in-depth). A `before_flush` hook
   stamps `org_id` on new rows, and a `do_orm_execute` hook adds a
   `with_loader_criteria` org filter — so SQLite dev (which has no RLS) still
   isolates, and inserts satisfy the RLS WITH CHECK.

Login / signup / bootstrap need to see across orgs (to find a user before we
know their org), so they run under `privileged()` — sessions then bind to the
superuser engine, which bypasses RLS.
"""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session, with_loader_criteria

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.getenv("AGENTIRA_DB_URL", f"sqlite:///{DATA_DIR / 'agentira.db'}")
_is_sqlite = DATABASE_URL.startswith("sqlite")

# Non-superuser app connection used for scoped (request-path) sessions so that
# Postgres RLS actually applies. When unset (dev / SQLite) we fall back to the
# privileged URL and rely on the app-layer belt only.
APP_DATABASE_URL = os.getenv("AGENTIRA_APP_DB_URL", DATABASE_URL)
_app_is_postgres = APP_DATABASE_URL.startswith("postgres")

_connect_args = {"check_same_thread": False} if _is_sqlite else {}
# Pool sizing for Postgres: several background schedulers (conductor tick,
# planning turn, progress check, stale-run reconciler, dispatch-outbox sweep)
# each open sync sessions from their own threads, on top of request-path
# sessions. The default pool_size=5/no-pre_ping was too small — under any
# query latency spike, background jobs alone can exhaust it, so every HTTP
# request then blocks up to pool_timeout waiting for a connection and the
# whole app looks dead (prod incident 2026-07-07). pool_pre_ping recycles
# connections Railway/Postgres dropped silently instead of erroring on use.
_pool_kwargs = {} if _is_sqlite else {
    "pool_pre_ping": True,
    "pool_size": 20,
    "max_overflow": 20,
    "pool_recycle": 1800,
}
# Privileged engine — superuser; bypasses RLS. Used for bootstrap, migrations,
# login and any explicitly-privileged cross-org work.
engine = create_engine(DATABASE_URL, echo=False, connect_args=_connect_args, **_pool_kwargs)
# Scoped engine — runs as the app role so RLS is enforced. Identical to the
# privileged engine when AGENTIRA_APP_DB_URL is unset (dev).
app_engine = (
    engine if APP_DATABASE_URL == DATABASE_URL
    else create_engine(APP_DATABASE_URL, echo=False, **_pool_kwargs)
)


# ── Tenancy context ────────────────────────────────────────────────────────
# Set per-request from the JWT's org claim. `privileged` lifts org scoping for
# cross-org operations (login, signup, bootstrap, migrations).

_current_org: ContextVar[str | None] = ContextVar("current_org", default=None)
_privileged: ContextVar[bool] = ContextVar("privileged", default=False)


def set_current_org(org_id: str | None) -> None:
    _current_org.set(org_id)


def get_current_org() -> str | None:
    return _current_org.get()


@contextmanager
def privileged():
    """Run a block with org scoping lifted (binds sessions to the superuser
    engine; RLS bypassed). For login, signup, bootstrap and admin cross-org
    work only."""
    token = _privileged.set(True)
    try:
        yield
    finally:
        _privileged.reset(token)


class Base(DeclarativeBase):
    pass


def _org_scoped_classes() -> set:
    """Mapped classes carrying an `org_id` column (the tenancy boundary)."""
    classes = set()
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if "org_id" in mapper.columns:
            classes.add(cls)
    return classes


class RoutingSession(Session):
    """Routes to the scoped (app-role, RLS-enforced) engine when there's a
    request org context, else to the privileged (superuser) engine.

    Rationale: request handlers always set an org (from the JWT), so they get
    RLS. Background/system work (Conductor loops, daemon, bootstrap) has no org
    context and runs privileged — it would otherwise see nothing under RLS.
    `privileged()` forces the superuser engine explicitly (login/signup)."""

    def get_bind(self, mapper=None, clause=None, **kw):
        if _privileged.get() or _current_org.get() is None:
            return engine
        return app_engine


SessionLocal = sessionmaker(
    class_=RoutingSession, autoflush=False, autocommit=False,
)


@event.listens_for(SessionLocal, "after_begin")
def _set_rls_org(session, transaction, connection):
    """At transaction start on a scoped Postgres connection, pin app.org so
    RLS policies resolve to the current org. No-op when privileged, on SQLite,
    or when no org is set (privileged/auth context)."""
    if _privileged.get():
        return
    if connection.dialect.name != "postgresql":
        return
    org = _current_org.get()
    # set_config(..., true) => LOCAL to this transaction; auto-resets on commit
    # so pooled connections never leak one org's setting into another.
    connection.execute(text("SELECT set_config('app.org', :o, true)"),
                        {"o": org or ""})


@event.listens_for(SessionLocal, "do_orm_execute")
def _org_filter(orm_execute_state):
    """App-layer org filter for SELECTs (dev parity with RLS). Skipped when
    privileged or when no org context is set."""
    if _privileged.get() or not orm_execute_state.is_select:
        return
    org = _current_org.get()
    if org is None:
        return
    for cls in _org_scoped_classes():
        orm_execute_state.statement = orm_execute_state.statement.options(
            with_loader_criteria(cls, lambda c: c.org_id == org,
                                 include_aliases=True)
        )


@event.listens_for(SessionLocal, "before_flush")
def _stamp_org(session, flush_context, instances):
    """Stamp org_id on new org-scoped rows from the current context so RLS
    WITH CHECK passes and callers don't have to set it everywhere."""
    if _privileged.get():
        return
    org = _current_org.get()
    if org is None:
        return
    for obj in session.new:
        if hasattr(obj, "org_id") and getattr(obj, "org_id", None) is None:
            obj.org_id = org


def get_db():
    """Yield a database session (FastAPI dependency)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def wait_for_db(*, attempts: int = 30, delay_seconds: float = 2.0) -> None:
    """Block until the database accepts a connection (or give up).

    On Railway the private network (`*.railway.internal`) isn't resolvable in
    the first second or two of a container's life, so connecting at startup
    races the network and fails with a DNS error. SQLite is always local, so
    this is a no-op there. Retries with a fixed backoff before letting the
    real error surface."""
    if _is_sqlite:
        return
    import logging
    import time
    log = logging.getLogger("agentira.db")
    last_exc: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            if i > 1:
                log.info("Database reachable after %d attempt(s).", i)
            return
        except Exception as exc:  # noqa: BLE001 — retry any connection failure
            last_exc = exc
            log.warning("Database not ready (attempt %d/%d): %s",
                        i, attempts, exc.__class__.__name__)
            time.sleep(delay_seconds)
    raise RuntimeError(
        f"Database unreachable after {attempts} attempts") from last_exc


def init_db():
    """Create all tables."""
    from backend.models import (  # noqa: F401
        Org, Invite, Project, Task, Activity, Epic, OAuthAccount, ProjectRepo,
        Milestone, TaskDependency,
    )
    from backend.forge.models import (  # noqa: F401
        Agent, Run, ForgeRuntime, TransitionEvent, GateEvaluation,
    )
    Base.metadata.create_all(bind=engine)
    run_migrations()


# Tables carrying org_id — the tenancy boundary. Order doesn't matter for the
# column-add/backfill; RLS is applied to each independently.
_ORG_SCOPED_TABLES = [
    "profiles", "oauth_accounts", "project_members", "notifications",
    "projects", "project_repos", "epics", "tasks", "task_commits",
    "task_dependencies", "milestones",
    "activities", "attachments", "profile_permissions",
    "forge_agents", "forge_runtimes", "deploy_credentials",
]

# Default org id used to backfill pre-tenancy rows so org_id can go NOT NULL.
# A deliberate split (per real owner) is done by scripts/setup_rls.py.
# NOTE: id columns are VARCHAR(12) — keep this exactly 12 chars.
_DEFAULT_ORG_ID = "orgdefault00"
_APP_ROLE = "agentira_app"


def _migrate_orgs(conn: Connection) -> None:
    """Add org_id to scoped tables, backfill a default org, enforce NOT NULL,
    then apply Postgres RLS. Idempotent; safe on every boot.

    Only meaningful on Postgres — SQLite dev relies on the app-layer belt and
    skips RLS entirely."""
    tables = _list_tables(conn)
    if "orgs" not in tables:
        return  # create_all hasn't made the table yet (shouldn't happen)

    is_pg = _dialect_name() == "postgresql"

    # 1) Add org_id column (nullable for now) to each scoped table.
    added_any = False
    for t in _ORG_SCOPED_TABLES:
        if t in tables:
            added_any |= _ensure_column(conn, t, "org_id", "VARCHAR(12)")
    if added_any:
        conn.commit()

    # 2) Ensure a default org exists, then backfill any NULL org_id to it so
    #    the NOT NULL constraint can hold. New deploys (org_id already set via
    #    create_all on fresh tables) skip the backfill.
    needs_backfill = any(
        conn.execute(text(f"SELECT 1 FROM {t} WHERE org_id IS NULL LIMIT 1")).first()
        for t in _ORG_SCOPED_TABLES if t in tables
    )
    if needs_backfill:
        exists = conn.execute(text("SELECT 1 FROM orgs WHERE id = :i"),
                              {"i": _DEFAULT_ORG_ID}).first()
        if not exists:
            # max_members/max_agents are NOT NULL with only a Python-side
            # default, so a raw INSERT must set them explicitly.
            conn.execute(text(
                "INSERT INTO orgs (id, name, max_members, max_agents, created_at) "
                "VALUES (:i, 'Default Org', 5, 5, CURRENT_TIMESTAMP)"
            ), {"i": _DEFAULT_ORG_ID})
        for t in _ORG_SCOPED_TABLES:
            if t in tables:
                conn.execute(text(
                    f"UPDATE {t} SET org_id = :o WHERE org_id IS NULL"
                ), {"o": _DEFAULT_ORG_ID})
        conn.commit()

    # 3) Enforce NOT NULL (Postgres only; SQLite can't ALTER COLUMN and the
    #    belt + fresh-table schema cover it there).
    if is_pg:
        for t in _ORG_SCOPED_TABLES:
            if t in tables and not _column_is_not_null(conn, t, "org_id"):
                # Guard: only flip when no NULLs remain.
                has_null = conn.execute(text(
                    f"SELECT 1 FROM {t} WHERE org_id IS NULL LIMIT 1")).first()
                if not has_null:
                    conn.execute(text(
                        f"ALTER TABLE {t} ALTER COLUMN org_id SET NOT NULL"))
        conn.commit()

    # 3b) profiles.name: global-unique → per-org-unique, so every org can have
    #     its own "Conductor"/"Planner"/etc. Idempotent.
    if is_pg and "profiles" in tables:
        # Drop the old global unique on name (auto-named profiles_name_key),
        # whatever it's called, then add the composite (org_id, name).
        rows = conn.execute(text(
            "SELECT con.conname FROM pg_constraint con "
            "JOIN pg_class rel ON rel.oid = con.conrelid "
            "WHERE rel.relname = 'profiles' AND con.contype = 'u'"
        )).all()
        for (conname,) in rows:
            # Identify the single-column unique on `name` and drop it.
            cols = conn.execute(text(
                "SELECT a.attname FROM pg_constraint con "
                "JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey) "
                "WHERE con.conname = :c"), {"c": conname}).all()
            colnames = {c[0] for c in cols}
            if colnames == {"name"}:
                conn.execute(text(f'ALTER TABLE profiles DROP CONSTRAINT "{conname}"'))
        # Add the per-org unique if not present.
        exists = conn.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conname = 'uq_profiles_org_name'"
        )).first()
        if not exists:
            conn.execute(text(
                "ALTER TABLE profiles ADD CONSTRAINT uq_profiles_org_name "
                "UNIQUE (org_id, name)"))
        conn.commit()

    # 4) Apply RLS policies (Postgres only).
    if is_pg:
        _apply_rls(conn)


def _apply_rls(conn: Connection) -> None:
    """Enable + FORCE row-level security on each scoped table with an org
    isolation policy keyed on the per-transaction `app.org` GUC. Idempotent.

    The app role (`agentira_app`) is granted table CRUD if it exists — its
    creation + the AGENTIRA_APP_DB_URL wiring is done once by
    scripts/setup_rls.py (needs a password we don't bake into code)."""
    role_exists = conn.execute(text(
        "SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": _APP_ROLE}).first()

    for t in _ORG_SCOPED_TABLES:
        conn.execute(text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
        # FORCE so even the table owner is subject (defence-in-depth; the app
        # role isn't owner anyway).
        conn.execute(text(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY"))
        # Drop+recreate the policy so edits to the predicate take on redeploy.
        conn.execute(text(f"DROP POLICY IF EXISTS org_iso ON {t}"))
        conn.execute(text(
            f"CREATE POLICY org_iso ON {t} "
            f"USING (org_id = current_setting('app.org', true)) "
            f"WITH CHECK (org_id = current_setting('app.org', true))"
        ))
        if role_exists:
            conn.execute(text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {_APP_ROLE}"))
    if role_exists:
        # Global (non-scoped) tables the app must still read/write.
        for t in ("orgs", "invites", "roles", "permissions", "role_permissions",
                  "statuses", "forge_runs", "forge_messages",
                  "forge_conversations", "forge_queued_messages",
                  "forge_webhook_logs"):
            if t in _list_tables(conn):
                conn.execute(text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {_APP_ROLE}"))
    conn.commit()


# ── Dialect-aware helpers ────────────────────────────────────────────────
# Migrations need to run against both SQLite (dev) and Postgres (qa/prod).
# These helpers hide the dialect-specific syntax so the migration steps
# below stay readable and don't sprout `if _is_sqlite:` everywhere.

def _dialect_name() -> str:
    return engine.dialect.name  # 'sqlite' | 'postgresql' | …


def _list_tables(conn: Connection) -> set[str]:
    if _dialect_name() == "sqlite":
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    else:
        rows = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        ))
    return {r[0] for r in rows}


def _columns_of(conn: Connection, table: str) -> set[str]:
    if _dialect_name() == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table})"))
        return {r[1] for r in rows}
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :t"
        ),
        {"t": table},
    )
    return {r[0] for r in rows}


def _column_is_not_null(conn: Connection, table: str, column: str) -> bool:
    """Whether `column` carries a NOT NULL constraint on this DB."""
    if _dialect_name() == "sqlite":
        rows = list(conn.execute(text(f"PRAGMA table_info({table})")))
        col = next((r for r in rows if r[1] == column), None)
        return bool(col and col[3] == 1)  # `notnull` flag
    row = conn.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).first()
    return bool(row and row[0] == "NO")


def _add_column(conn: Connection, table: str, column: str, type_sql: str) -> None:
    """ALTER TABLE … ADD COLUMN — same syntax on both SQLite and Postgres."""
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {type_sql}"))


def _ensure_column(conn: Connection, table: str, column: str, type_sql: str) -> bool:
    """Idempotent: add `column` if it doesn't already exist. Returns True if added."""
    if column in _columns_of(conn, table):
        return False
    _add_column(conn, table, column, type_sql)
    return True


def _drop_not_null(conn: Connection, table: str, column: str) -> None:
    """Idempotent on Postgres; on SQLite this is a no-op (caller must table-rebuild)."""
    if _dialect_name() == "postgresql":
        conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL"))


def _backfill_primary_project_repo(conn: Connection) -> None:
    """AP-121: one-shot backfill — every project with a legacy
    repo_path/repo_url AND no project_repos row yet gets a primary
    row built from those values. Idempotent on rerun (skips projects
    that already have any repo)."""
    import uuid
    rows = conn.execute(text(
        "SELECT id, org_id, repo_path, repo_url FROM projects "
        "WHERE id NOT IN (SELECT DISTINCT project_id FROM project_repos)"
    )).all()
    for project_id, org_id, repo_path, repo_url in rows:
        if not (repo_path or repo_url):
            continue
        conn.execute(text(
            "INSERT INTO project_repos (id, org_id, project_id, name, repo_path, "
            "                            repo_url, default_branch, "
            "                            is_primary, created_at) "
            "VALUES (:id, :oid, :pid, 'primary', :rp, :ru, 'main', :pri, "
            "        CURRENT_TIMESTAMP)"
        ), {"id": uuid.uuid4().hex[:12], "oid": org_id, "pid": project_id,
            "rp": repo_path, "ru": repo_url, "pri": True})
    if rows:
        conn.commit()


def backfill_workspace_kind(conn: Connection) -> None:
    """AP-414: a project with a repo is a git workspace, not a sandbox.

    `workspace_kind` was stamped once and never revisited, so attaching a repo
    through `project_repos` left the project on 'sandbox' — which blanks the
    worktree fields at dispatch and drops the agent into an empty directory.
    Flip those rows (repo_url on the project, or any project_repos row with a
    remote URL). Idempotent."""
    conn.execute(text(
        "UPDATE projects SET workspace_kind='git' "
        "WHERE workspace_kind='sandbox' AND ("
        "  (repo_url IS NOT NULL AND repo_url<>'') OR id IN ("
        "    SELECT project_id FROM project_repos "
        "    WHERE repo_url IS NOT NULL AND repo_url<>''))"))


def _derive_account_type(role_name, runtime_id) -> str:
    """Map a legacy (role_name, runtime_id) pair to a stored account_type.

    Used by the one-shot RBAC backfill. The retired 'bot' role split into two
    account types by whether the profile is dispatched (has a runtime)."""
    if role_name == "bot":
        return "agentira_agent" if runtime_id else "external_agent"
    return "human"


def _migrate_rbac_account_types(conn: Connection) -> None:
    """One-shot: legacy single-`role_id` schema → stored `account_type` +
    many-to-many `profile_roles`.

    Backfills account_type from (role, runtime_id), copies each profile's single
    role into profile_roles (the retired 'bot' role remaps to 'member'), drops
    profiles.role_id, and deletes the 'bot' role. Guarded by role_id's presence
    so it no-ops once applied and on fresh (create_all) DBs."""
    if "role_id" not in _columns_of(conn, "profiles"):
        return
    is_pg = _dialect_name() == "postgresql"
    rows = conn.execute(text(
        "SELECT p.id, r.name, p.runtime_id, p.role_id "
        "FROM profiles p JOIN roles r ON p.role_id = r.id")).all()
    member_id = conn.execute(text("SELECT id FROM roles WHERE name='member'")).scalar()
    insert_sql = ("INSERT INTO profile_roles (profile_id, role_id) VALUES (:p, :r) "
                  + ("ON CONFLICT DO NOTHING" if is_pg else ""))
    if not is_pg:
        insert_sql = insert_sql.replace("INSERT INTO", "INSERT OR IGNORE INTO")
    for pid, rname, runtime_id, role_id in rows:
        conn.execute(text("UPDATE profiles SET account_type = :a WHERE id = :i"),
                     {"a": _derive_account_type(rname, runtime_id), "i": pid})
        target = member_id if rname == "bot" else role_id
        if target:
            conn.execute(text(insert_sql), {"p": pid, "r": target})
    if is_pg:
        conn.execute(text("ALTER TABLE profiles DROP COLUMN role_id"))
    # Remove the retired 'bot' role (its grants first — no guaranteed FK cascade).
    conn.execute(text("DELETE FROM role_permissions WHERE role_id IN "
                      "(SELECT id FROM roles WHERE name = 'bot')"))
    conn.execute(text("DELETE FROM roles WHERE name = 'bot'"))


def _migrate_forge_agents_to_profiles(conn: Connection) -> None:
    """AP-86 bot/agent merge: each forge_agent becomes a 1:1 profile.

    Destructive: when multiple forge_agents share a profile, we split — only
    the first keeps the shared profile; the rest get new profiles named
    after the agent (collision-renamed if needed). Runtime config moves
    onto the resulting profiles. forge_runs.agent_id and forge_messages.agent_id
    are repointed via the agent→profile mapping. forge_agents table is
    NOT dropped here (code still queries it during transition); a follow-up
    drops it after the code paths migrate.
    """
    # Post-RBAC schema has no role_id and no 'bot' role — this legacy AP-86
    # path inserts role_id, so it only applies to pre-RBAC databases.
    if "role_id" not in _columns_of(conn, "profiles"):
        return
    role_row = conn.execute(text("SELECT id FROM roles WHERE name = 'bot' LIMIT 1")).first()
    if not role_row:
        return  # no bot role; nothing to do (fresh DBs handled by create_all)
    bot_role_id = role_row[0]

    # Iterate forge_agents in stable order (creation order) — first-wins for shared profile.
    agents = list(conn.execute(text(
        "SELECT id, name, profile_id, model, system_prompt, personality, "
        "       runtime_id, default_project_id, mcp_servers "
        "FROM forge_agents ORDER BY created_at"
    )))
    profile_taken: set[str] = set()  # profile_ids already claimed (1:1 enforcement)
    # agent_id → resolved profile_id (used to repoint runs/messages)
    agent_to_profile: dict[str, str] = {}

    for (agent_id, agent_name, profile_id, model, system_prompt,
         personality, runtime_id, default_project_id, mcp_servers) in agents:
        target_pid = None
        if profile_id and profile_id not in profile_taken:
            # First agent on this profile — adopt it.
            target_pid = profile_id
            profile_taken.add(profile_id)
        else:
            # Either no profile_id, or the profile's already claimed.
            # Create a fresh profile with a unique name derived from the agent.
            base_name = (agent_name or agent_id)[:80] or "agent"
            unique_name = base_name
            suffix = 0
            while conn.execute(text(
                "SELECT 1 FROM profiles WHERE name = :n"
            ), {"n": unique_name}).first():
                suffix += 1
                unique_name = f"{base_name}-{suffix}"
            target_pid = agent_id  # reuse the agent's id as the new profile id
            if conn.execute(text("SELECT 1 FROM profiles WHERE id = :i"),
                           {"i": target_pid}).first():
                # Profile with that id already exists — bail to a fresh id.
                import uuid
                target_pid = uuid.uuid4().hex[:12]
            conn.execute(text(
                "INSERT INTO profiles (id, name, display_name, password_hash, "
                "                      avatar_url, webhook_url, role_id, created_at) "
                "VALUES (:i, :n, :d, '', '', '', :r, CURRENT_TIMESTAMP)"
            ), {"i": target_pid, "n": unique_name, "d": agent_name or unique_name,
                "r": bot_role_id})
            profile_taken.add(target_pid)

        # Copy the runtime config onto target_pid.
        conn.execute(text(
            "UPDATE profiles SET model = :m, system_prompt = :sp, "
            "  personality = :p, runtime_id = :rt, "
            "  default_project_id = :dp, mcp_servers = :mcp "
            "WHERE id = :i"
        ), {
            "i": target_pid,
            "m": model or "",
            "sp": system_prompt,
            "p": personality,
            "rt": runtime_id,
            "dp": default_project_id,
            "mcp": mcp_servers,
        })
        agent_to_profile[agent_id] = target_pid

    # Also update forge_agents.profile_id so legacy queries still resolve
    # to the dedicated 1:1 profile (not the original shared one).
    for agent_id, pid in agent_to_profile.items():
        conn.execute(text(
            "UPDATE forge_agents SET profile_id = :p WHERE id = :a"
        ), {"p": pid, "a": agent_id})

    # Repoint forge_runs.agent_id and forge_messages.agent_id to the
    # resolved profile_id. We do this by adding a profile_id column and
    # writing the mapping; the columns are populated NOW so subsequent
    # code can read profile_id, and we drop the old agent_id later.
    tables = _list_tables(conn)
    if "forge_runs" in tables:
        _ensure_column(conn, "forge_runs", "profile_id", "VARCHAR(12)")
        for agent_id, pid in agent_to_profile.items():
            conn.execute(text(
                "UPDATE forge_runs SET profile_id = :p WHERE agent_id = :a"
            ), {"p": pid, "a": agent_id})
    if "forge_messages" in tables:
        _ensure_column(conn, "forge_messages", "profile_id", "VARCHAR(12)")
        for agent_id, pid in agent_to_profile.items():
            conn.execute(text(
                "UPDATE forge_messages SET profile_id = :p WHERE agent_id = :a"
            ), {"p": pid, "a": agent_id})
    conn.commit()


def run_migrations():
    """Apply incremental schema changes — runs on every dialect.

    Schemas are still authoritative via SQLAlchemy `create_all`. These
    migrations cover the gap for existing databases that need to gain
    new columns / drop NOT NULL constraints.
    """
    with engine.connect() as conn:
        tables = _list_tables(conn)

        # activities
        if "activities" in tables:
            if _ensure_column(conn, "activities", "diff", "TEXT"):
                conn.commit()

        # profiles
        if "profiles" in tables:
            added = False
            added |= _ensure_column(conn, "profiles", "webhook_url", "VARCHAR(500) DEFAULT ''")
            added |= _ensure_column(conn, "profiles", "notification_transport", "VARCHAR(20)")
            added |= _ensure_column(conn, "profiles", "email", "VARCHAR(255)")
            # AP-306: password lifecycle + forgot-password tokens
            added |= _ensure_column(conn, "profiles", "must_change_password", "BOOLEAN DEFAULT FALSE NOT NULL")
            added |= _ensure_column(conn, "profiles", "reset_token", "VARCHAR(64)")
            added |= _ensure_column(conn, "profiles", "reset_token_expires", "TIMESTAMPTZ")
            # Older installs created it as naive TIMESTAMP; the model is
            # tz-aware, so comparing against now(utc) crashed. Values are UTC.
            if _dialect_name() == "postgresql" and conn.execute(text(
                    "SELECT data_type FROM information_schema.columns WHERE table_name='profiles' "
                    "AND column_name='reset_token_expires'")).scalar() == "timestamp without time zone":
                conn.execute(text("ALTER TABLE profiles ALTER COLUMN reset_token_expires "
                                  "TYPE TIMESTAMPTZ USING reset_token_expires AT TIME ZONE 'UTC'"))
            # RBAC remodel: stored account type, decoupled from roles.
            added |= _ensure_column(conn, "profiles", "account_type", "VARCHAR(20) DEFAULT 'human' NOT NULL")
            # AP-86: bot/agent merge — runtime config moves onto profile
            runtime_added = False
            runtime_added |= _ensure_column(conn, "profiles", "model", "VARCHAR(120) DEFAULT ''")
            runtime_added |= _ensure_column(conn, "profiles", "system_prompt", "TEXT")
            runtime_added |= _ensure_column(conn, "profiles", "personality", "TEXT")
            runtime_added |= _ensure_column(conn, "profiles", "runtime_id", "VARCHAR(12)")
            runtime_added |= _ensure_column(conn, "profiles", "default_project_id", "VARCHAR(12)")
            runtime_added |= _ensure_column(conn, "profiles", "mcp_servers", "TEXT")
            # forge_messages.scope_key — conversation-isolation column
            if "forge_messages" in tables:
                _ensure_column(conn, "forge_messages", "scope_key", "VARCHAR(120)")
            runtime_added |= _ensure_column(conn, "profiles", "mcp_disabled", "TEXT")
            runtime_added |= _ensure_column(conn, "profiles", "mcp_strict", "BOOLEAN DEFAULT FALSE NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "mcp_config_override", "TEXT")
            runtime_added |= _ensure_column(conn, "profiles", "env_vars", "TEXT")
            runtime_added |= _ensure_column(conn, "profiles", "home_path", "VARCHAR(500)")
            # AP-80 Conductor: opt-in autonomous task pickup
            runtime_added |= _ensure_column(conn, "profiles", "conductor_enabled", "BOOLEAN DEFAULT FALSE NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "max_concurrent_runs", "INTEGER DEFAULT 1 NOT NULL")
            # System agents (Conductor, Concierge) + Conductor cadence config
            runtime_added |= _ensure_column(conn, "profiles", "is_system", "BOOLEAN DEFAULT FALSE NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "conductor_tick_seconds", "INTEGER DEFAULT 60 NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "conductor_report_time", "VARCHAR(5) DEFAULT '09:00' NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "conductor_report_enabled", "BOOLEAN DEFAULT TRUE NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "conductor_plan_interval_minutes", "INTEGER DEFAULT 10 NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "conductor_active", "BOOLEAN DEFAULT TRUE NOT NULL")
            # Runaway-guard recovery policy: cooldown + attempt cap for
            # re-picking a FAILED/CANCELLED task's auto-dispatch.
            runtime_added |= _ensure_column(conn, "profiles", "conductor_redispatch_cooldown_minutes", "INTEGER DEFAULT 30 NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "conductor_redispatch_max_attempts", "INTEGER DEFAULT 3 NOT NULL")
            # AP-155: agent-level sandbox containment mode.
            runtime_added |= _ensure_column(conn, "profiles", "sandbox_mode", "VARCHAR(20)")
            # AP-302: personal git access token + cached validity.
            runtime_added |= _ensure_column(conn, "profiles", "git_token", "VARCHAR(500)")
            runtime_added |= _ensure_column(conn, "profiles", "git_token_valid", "BOOLEAN")
            runtime_added |= _ensure_column(conn, "profiles", "git_token_checked_at", "TIMESTAMP")
            if added or runtime_added:
                conn.commit()
            # Backfill: copy runtime config from forge_agents onto its linked
            # profile so future reads can use profile.* directly. Idempotent —
            # only fills nulls; explicit profile writes are preserved.
            # AP-86 bot/agent merge — run once when forge_agents still exists
            # AND we haven't yet migrated (no profile_id column on forge_runs).
            if "forge_agents" in tables and "forge_runs" in tables \
               and "profile_id" not in _columns_of(conn, "forge_runs"):
                _migrate_forge_agents_to_profiles(conn)
            # RBAC remodel: single role_id → account_type + profile_roles M2M.
            # No-ops (guarded) once applied and on fresh create_all databases.
            _migrate_rbac_account_types(conn)
            conn.commit()

        # OAuth accounts table — `create_all` makes this for us when
        # the model is registered, so we don't bootstrap it here anymore.

        # projects
        if "projects" in tables:
            added = False
            added |= _ensure_column(conn, "projects", "webhook_config", "TEXT")
            added |= _ensure_column(conn, "projects", "repo_path", "VARCHAR(500)")
            added |= _ensure_column(conn, "projects", "repo_url", "VARCHAR(500)")
            added |= _ensure_column(conn, "projects", "conventions_md", "TEXT")
            # AP-4: template provenance + AC check registry.
            added |= _ensure_column(conn, "projects", "template_name",
                                    "VARCHAR(120)")
            added |= _ensure_column(conn, "projects", "ac_check_types_json",
                                    "TEXT")
            # ADR 009 / AP-136: work-signal mode for run crystallization.
            added |= _ensure_column(conn, "projects", "work_signal", "VARCHAR(20)")
            # AP-155: project-level sandbox containment override.
            added |= _ensure_column(conn, "projects", "sandbox_mode", "VARCHAR(20)")
            # AP-308: per-run environment isolation (mode + override cmds/url).
            added |= _ensure_column(conn, "projects", "env_isolation", "VARCHAR(20)")
            added |= _ensure_column(conn, "projects", "env_setup_cmd", "TEXT")
            added |= _ensure_column(conn, "projects", "env_teardown_cmd", "TEXT")
            added |= _ensure_column(conn, "projects", "env_db_admin_url", "VARCHAR(500)")
            # AP-158: per-project gate-engine toggle.
            added |= _ensure_column(conn, "projects", "gates_enabled", "BOOLEAN DEFAULT FALSE NOT NULL")
            # AP-197: workspace kind (git | sandbox | local_folder). NULL =
            # inferred at dispatch. Backfilled below from existing repo fields.
            if _ensure_column(conn, "projects", "workspace_kind", "VARCHAR(20)"):
                added = True
                conn.execute(text(
                    "UPDATE projects SET workspace_kind='git' "
                    "WHERE workspace_kind IS NULL "
                    "AND repo_url IS NOT NULL AND repo_url<>''"))
                conn.execute(text(
                    "UPDATE projects SET workspace_kind='local_folder' "
                    "WHERE workspace_kind IS NULL "
                    "AND repo_path IS NOT NULL AND repo_path<>''"))
                conn.execute(text(
                    "UPDATE projects SET workspace_kind='sandbox' "
                    "WHERE workspace_kind IS NULL"))
            # AP-414: projects that got a repo AFTER the column was stamped
            # still read 'sandbox' — which provisions an empty dir. Flip them.
            backfill_workspace_kind(conn)
            # Workflow driver: per-project opt-in + the restricted customer
            # override (role->agent mapping only; the flow is system config).
            added |= _ensure_column(conn, "projects", "workflow_enabled",
                                    "BOOLEAN DEFAULT FALSE NOT NULL")
            added |= _ensure_column(conn, "projects", "workflow_roles_json", "TEXT")
            # Per-project prompt-text overrides for workflow hand-off prompts.
            added |= _ensure_column(conn, "projects", "workflow_prompts_json", "TEXT")
            # AP-297: per-project TTL for cached pre-run checks (NULL = 600s
            # default; 0 = no time expiry, env-change re-runs only).
            added |= _ensure_column(conn, "projects", "ready_checks_ttl_seconds",
                                    "INTEGER")
            # Single-repo deploy target. kind picks the adapter; config_json is
            # opaque per-kind (adding a provider = new adapter, not a migration).
            added |= _ensure_column(conn, "projects", "deploy_target_kind",
                                    "VARCHAR(20) DEFAULT 'railway' NOT NULL")
            added |= _ensure_column(conn, "projects", "deploy_target_config_json",
                                    "TEXT")
        # AP-121: tasks gain repo_name pointing at one of the project's repos.
        # AP-154: tasks gain repos_json — JSON list when a task touches more
        # than one of the project's repos. NULL stays back-compat with
        # repo_name-only callers (sandbox helper derives a single-item list).
        if "tasks" in tables:
            _ensure_column(conn, "tasks", "repo_name", "VARCHAR(60)")
            _ensure_column(conn, "tasks", "repos_json", "TEXT")
        # AP-121: backfill — for every project with a legacy repo_path /
        # repo_url and no project_repos rows, insert one primary row.
        # Runs after `Base.metadata.create_all` has created project_repos.
        if "projects" in tables and "project_repos" in tables:
            # AP-296: per-repo worktree freshness policy (always_latest default).
            if _ensure_column(conn, "project_repos", "worktree_freshness",
                              "VARCHAR(20)"):
                added = True
            _backfill_primary_project_repo(conn)
            if added:
                conn.commit()

        # AP-507: dependency edges gain a link type.
        if "task_dependencies" in tables:
            if _ensure_column(conn, "task_dependencies", "link_type",
                              "VARCHAR(20) DEFAULT 'depends_on' NOT NULL"):
                conn.commit()

        # AP-302: project_repos gain a git access token + cached validity.
        if "project_repos" in tables:
            repo_added = False
            repo_added |= _ensure_column(conn, "project_repos", "access_token", "VARCHAR(500)")
            repo_added |= _ensure_column(conn, "project_repos", "token_valid", "BOOLEAN")
            repo_added |= _ensure_column(conn, "project_repos", "token_checked_at", "TIMESTAMP")
            if repo_added:
                conn.commit()

        # tasks
        if "tasks" in tables:
            added = False
            added |= _ensure_column(conn, "tasks", "dod_items", "TEXT")
            added |= _ensure_column(conn, "tasks", "branch", "VARCHAR(255) DEFAULT ''")
            added |= _ensure_column(conn, "tasks", "pr_url", "VARCHAR(500) DEFAULT ''")
            added |= _ensure_column(conn, "tasks", "start_date", "TIMESTAMP")
            added |= _ensure_column(conn, "tasks", "due_date", "TIMESTAMP")
            added |= _ensure_column(conn, "tasks", "epic_id", "VARCHAR(12)")
            added |= _ensure_column(conn, "tasks", "creator", "VARCHAR(120) DEFAULT ''")
            # Task type discriminator (task | bug | ...) — DEFAULT backfills existing rows.
            added |= _ensure_column(conn, "tasks", "type", "VARCHAR(20) DEFAULT 'task' NOT NULL")
            # AP-496: child tasks + roadmap milestone rollup.
            added |= _ensure_column(conn, "tasks", "parent_id", "VARCHAR(12)")
            added |= _ensure_column(conn, "tasks", "milestone_id", "VARCHAR(12)")
            # Scope task-key uniqueness to (project_id, key) instead of globally.
            # Two orgs sharing a key prefix (e.g. both named "Pitch Fox" → "PF")
            # would collide on PF-1 with the old global constraint.
            # DO $$ block handles both constraint and bare-index forms atomically.
            if _dialect_name() == "postgresql":
                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = 'tasks_key_key'
                              AND conrelid = 'tasks'::regclass
                        ) THEN
                            ALTER TABLE tasks DROP CONSTRAINT tasks_key_key;
                        ELSIF EXISTS (
                            SELECT 1 FROM pg_indexes
                            WHERE tablename = 'tasks'
                              AND indexname = 'tasks_key_key'
                        ) THEN
                            DROP INDEX tasks_key_key;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = 'uq_tasks_project_key'
                              AND conrelid = 'tasks'::regclass
                        ) THEN
                            ALTER TABLE tasks ADD CONSTRAINT uq_tasks_project_key
                                UNIQUE (project_id, key);
                        END IF;
                    END
                    $$;
                """))
                added = True
            if added:
                conn.commit()

        # epics
        if "epics" in tables:
            if _ensure_column(conn, "epics", "creator", "VARCHAR(120) DEFAULT ''"):
                conn.commit()

        # attachments — AP-152: project-level attachments share the table.
        # `task_id` becomes nullable; new `project_id` FK added. A row carries
        # exactly one (XOR is enforced in `backend.attachments.add`).
        if "attachments" in tables:
            if _ensure_column(conn, "attachments", "project_id", "VARCHAR(12)"):
                conn.commit()
            # AP-351: epic-scoped attachments.
            if _ensure_column(conn, "attachments", "epic_id", "VARCHAR(12)"):
                conn.commit()
            if _column_is_not_null(conn, "attachments", "task_id"):
                if _dialect_name() == "postgresql":
                    _drop_not_null(conn, "attachments", "task_id")
                    conn.commit()
                else:
                    _sqlite_rebuild_attachments_task_id_nullable(conn)
                    conn.commit()

        # forge_runtimes — for SQLite-only legacy DBs we need to bootstrap
        # the table; on Postgres `create_all` handles fresh deploys cleanly
        # so this branch only matters for an existing SQLite DB upgrading.
        if "forge_runtimes" not in tables and _dialect_name() == "sqlite":
            conn.execute(text("""
                CREATE TABLE forge_runtimes (
                    id VARCHAR(12) PRIMARY KEY,
                    daemon_id VARCHAR(64) NOT NULL,
                    device_name VARCHAR(120),
                    provider VARCHAR(40) NOT NULL,
                    binary_path VARCHAR(500) NOT NULL,
                    version VARCHAR(80),
                    status VARCHAR(20) DEFAULT 'unknown',
                    capabilities TEXT,
                    last_heartbeat DATETIME,
                    created_at DATETIME,
                    UNIQUE(daemon_id, provider)
                )
            """))
            conn.commit()

        # forge_agents new columns
        if "forge_agents" in tables:
            added = False
            added |= _ensure_column(conn, "forge_agents", "runtime_id", "VARCHAR(12)")
            added |= _ensure_column(conn, "forge_agents", "schedule_cron", "VARCHAR(60)")
            added |= _ensure_column(conn, "forge_agents", "mcp_servers", "TEXT")
            added |= _ensure_column(conn, "forge_agents", "default_project_id", "VARCHAR(12)")
            if added:
                conn.commit()

        # forge_runs new columns
        if "forge_runs" in tables:
            added = False
            added |= _ensure_column(conn, "forge_runs", "session_id", "VARCHAR(80)")
            added |= _ensure_column(conn, "forge_runs", "workdir", "VARCHAR(500)")
            added |= _ensure_column(conn, "forge_runs", "outcome", "VARCHAR(20)")
            added |= _ensure_column(conn, "forge_runs", "summary", "TEXT")
            added |= _ensure_column(conn, "forge_runs", "diff_stat", "TEXT")
            added |= _ensure_column(conn, "forge_runs", "diff", "TEXT")
            added |= _ensure_column(conn, "forge_runs", "initial_prompt", "TEXT")
            added |= _ensure_column(conn, "forge_runs", "diagnostics_json", "TEXT")
            # P3: transient-state audit timestamp.
            added |= _ensure_column(conn, "forge_runs", "stop_requested_at",
                                    "TIMESTAMP")
            # AP-125: structured artifacts list (JSON).
            added |= _ensure_column(conn, "forge_runs", "artifacts_json", "TEXT")
            # AP-123: per-run worktree path + branch.
            added |= _ensure_column(conn, "forge_runs", "worktree_path",
                                    "VARCHAR(500)")
            added |= _ensure_column(conn, "forge_runs", "worktree_branch",
                                    "VARCHAR(255)")
            # ADR 009 / AP-137: parked steer message (chat-during-run).
            added |= _ensure_column(conn, "forge_runs", "pending_steer", "TEXT")
            # Materializer outcome from the daemon (ok / no_repo_path /
            # repo_path_not_found:<expanded>). Surfaced on the Run page.
            added |= _ensure_column(conn, "forge_runs", "materialize_reason",
                                    "VARCHAR(255)")
            # Per-run log directory (~/.agentira/runs/<run_id>/).
            added |= _ensure_column(conn, "forge_runs", "log_dir",
                                    "VARCHAR(500)")
            # AP-297: cached pre-run (ready) checks + their env signature/time.
            added |= _ensure_column(conn, "forge_runs", "ready_checks_json", "TEXT")
            added |= _ensure_column(conn, "forge_runs", "ready_checks_sig",
                                    "VARCHAR(64)")
            added |= _ensure_column(conn, "forge_runs", "ready_checks_at",
                                    "TIMESTAMP")
            if added:
                conn.commit()

        # forge_runtimes new columns
        if "forge_runtimes" in tables:
            added = False
            added |= _ensure_column(conn, "forge_runtimes", "models", "TEXT")
            added |= _ensure_column(conn, "forge_runtimes", "gateway_url", "VARCHAR(500)")
            added |= _ensure_column(conn, "forge_runtimes", "gateway_token", "VARCHAR(500)")
            added |= _ensure_column(conn, "forge_runtimes", "host_tools", "TEXT")
            if added:
                conn.commit()

        # forge_messages: trace_id + kind (Step 1 — one rail)
        if "forge_messages" in tables:
            if _ensure_column(conn, "forge_messages", "trace_id", "VARCHAR(12)"):
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_forge_messages_trace_id "
                    "ON forge_messages(trace_id)"
                ))
                conn.commit()
            if _ensure_column(conn, "forge_messages", "kind", "VARCHAR(20)"):
                conn.commit()

        # forge_agents.profile_id NOT NULL → NULLABLE.
        # Postgres: trivial ALTER COLUMN. SQLite: full table rebuild because
        # SQLite predates ALTER COLUMN.
        if "forge_agents" in tables and _column_is_not_null(conn, "forge_agents", "profile_id"):
            if _dialect_name() == "postgresql":
                _drop_not_null(conn, "forge_agents", "profile_id")
                conn.commit()
            else:
                _sqlite_rebuild_forge_agents_profile_id_nullable(conn)
                conn.commit()

        # AP-433: Task.project_id / Task.status_id gained index=True on the
        # model (#208), but create_all() only creates indexes as part of
        # creating a NEW table (checkfirst=True skips tables that already
        # exist) — on any real deploy `tasks` already exists, so the model
        # change alone never touches it. Board/backlog/list_tasks all filter
        # by project_id; add the indexes explicitly so that's true in prod.
        if "tasks" in tables:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_tasks_project_id ON tasks(project_id)"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_tasks_status_id ON tasks(status_id)"))
            # list_epics batch-counts tasks per epic_id (AP-433 N+1 fix,
            # replacing len(epic.tasks)) — index the column that query groups by.
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_tasks_epic_id ON tasks(epic_id)"))
            # AP-496: subtask + milestone rollups group by these columns.
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_tasks_parent_id ON tasks(parent_id)"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_tasks_milestone_id ON tasks(milestone_id)"))
            conn.commit()

        # AP-433: project_members.project_id is covered by the leading
        # column of the (project_id, profile_id) unique constraint, but the
        # reverse lookup (profile_id alone — Profile.project_memberships,
        # used by list_profiles/_profile_to_dict) isn't covered by that
        # composite index. Needed once list_profiles moves off per-row
        # lazy-loads.
        if "project_members" in tables:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_project_members_profile_id "
                "ON project_members(profile_id)"))
            conn.commit()

        # Multi-tenancy: org_id columns + backfill + Postgres RLS.
        _migrate_orgs(conn)


def _sqlite_rebuild_attachments_task_id_nullable(conn: Connection) -> None:
    """SQLite-only: rebuild `attachments` to drop NOT NULL on task_id.

    AP-152: project-scoped attachments need task_id NULL. SQLite can't
    ALTER COLUMN, so we rename → create_all-shaped fresh table → copy →
    drop. The fresh table mirrors `models.Attachment` (both FKs nullable).
    """
    cols = list(conn.execute(text("PRAGMA table_info(attachments)")))
    conn.execute(text("PRAGMA foreign_keys=OFF"))
    conn.execute(text("ALTER TABLE attachments RENAME TO attachments_old"))
    conn.execute(text("""
        CREATE TABLE attachments (
            id VARCHAR(12) PRIMARY KEY,
            task_id VARCHAR(12) REFERENCES tasks(id),
            project_id VARCHAR(12) REFERENCES projects(id),
            filename VARCHAR(255) NOT NULL,
            content_type VARCHAR(120) DEFAULT 'application/octet-stream',
            file_path VARCHAR(500) NOT NULL,
            size_bytes INTEGER DEFAULT 0,
            uploaded_by VARCHAR(120) DEFAULT 'system',
            created_at DATETIME
        )
    """))
    old_cols = [c[1] for c in cols]
    col_list = ", ".join(old_cols)
    conn.execute(text(f"INSERT INTO attachments ({col_list}) SELECT {col_list} FROM attachments_old"))
    conn.execute(text("DROP TABLE attachments_old"))
    conn.execute(text("PRAGMA foreign_keys=ON"))


def _sqlite_rebuild_forge_agents_profile_id_nullable(conn: Connection) -> None:
    """SQLite-only: rebuild forge_agents to drop NOT NULL on profile_id.

    SQLite doesn't support ALTER COLUMN, so the canonical workaround is:
    rename old table → create new with the desired schema → copy rows →
    drop old table.
    """
    cols = list(conn.execute(text("PRAGMA table_info(forge_agents)")))
    conn.execute(text("PRAGMA foreign_keys=OFF"))
    conn.execute(text("ALTER TABLE forge_agents RENAME TO forge_agents_old"))
    conn.execute(text("""
        CREATE TABLE forge_agents (
            id VARCHAR(12) PRIMARY KEY,
            profile_id VARCHAR(12) REFERENCES profiles(id),
            name VARCHAR(120) NOT NULL,
            executor_type VARCHAR(30) DEFAULT 'http',
            model VARCHAR(120) DEFAULT '',
            status VARCHAR(20) DEFAULT 'OFFLINE',
            webhook_url VARCHAR(500) DEFAULT '',
            last_heartbeat DATETIME,
            total_runs INTEGER DEFAULT 0,
            total_cost_usd FLOAT DEFAULT 0.0,
            config_json TEXT,
            system_prompt TEXT,
            personality TEXT,
            runtime_type VARCHAR(30),
            runtime_url VARCHAR(500),
            runtime_gateway_token VARCHAR(500),
            runtime_hooks_token VARCHAR(500),
            runtime_agent_name VARCHAR(120),
            schedule_start VARCHAR(10),
            schedule_end VARCHAR(10),
            schedule_tz VARCHAR(40),
            schedule_days VARCHAR(60),
            schedule_enabled BOOLEAN DEFAULT 0,
            schedule_cron VARCHAR(60),
            runtime_id VARCHAR(12) REFERENCES forge_runtimes(id),
            created_at DATETIME
        )
    """))
    old_cols = [c[1] for c in cols]
    col_list = ", ".join(old_cols)
    conn.execute(text(f"INSERT INTO forge_agents ({col_list}) SELECT {col_list} FROM forge_agents_old"))
    conn.execute(text("DROP TABLE forge_agents_old"))
    conn.execute(text("PRAGMA foreign_keys=ON"))


def bootstrap_schema(url: str) -> None:
    """AP-308: create the full current schema against an arbitrary DSN.

    Used by the daemon's per_run_db isolation to give a throwaway
    ``run_<id>`` database exact schema parity with the app — it shells out
    to ``python -m backend.db --bootstrap --url <dsn>`` so it never has to
    import the backend package. A fresh DB needs no incremental migrations;
    ``create_all`` from the live models IS the current schema.
    """
    from backend.models import (  # noqa: F401
        Org, Invite, Project, Task, Activity, Epic, OAuthAccount, ProjectRepo,
        Milestone, TaskDependency,
    )
    from backend.forge.models import (  # noqa: F401
        Agent, Run, ForgeRuntime, TransitionEvent, GateEvaluation,
    )
    target = create_engine(url, echo=False)
    try:
        Base.metadata.create_all(bind=target)
    finally:
        target.dispose()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="agentira db utilities")
    parser.add_argument("--bootstrap", action="store_true",
                        help="create the schema against --url and exit")
    parser.add_argument("--url", help="target DSN for --bootstrap")
    args = parser.parse_args()
    if args.bootstrap:
        if not args.url:
            parser.error("--bootstrap requires --url")
        bootstrap_schema(args.url)
        print(f"bootstrapped schema at {args.url}")
    else:
        parser.error("nothing to do (try --bootstrap --url <dsn>)")
