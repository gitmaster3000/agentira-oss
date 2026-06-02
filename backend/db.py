"""Database engine and session management."""

import os
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.getenv("AGENTIRA_DB_URL", f"sqlite:///{DATA_DIR / 'agentira.db'}")
_is_sqlite = DATABASE_URL.startswith("sqlite")

_connect_args = {"check_same_thread": False} if _is_sqlite else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """Yield a database session (FastAPI dependency)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables."""
    from backend.models import Project, Task, Activity, Epic, OAuthAccount, ProjectRepo  # noqa: F401
    from backend.forge.models import Agent, Run, ForgeRuntime  # noqa: F401
    Base.metadata.create_all(bind=engine)
    run_migrations()


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
        "SELECT id, repo_path, repo_url FROM projects "
        "WHERE id NOT IN (SELECT DISTINCT project_id FROM project_repos)"
    )).all()
    for project_id, repo_path, repo_url in rows:
        if not (repo_path or repo_url):
            continue
        conn.execute(text(
            "INSERT INTO project_repos (id, project_id, name, repo_path, "
            "                            repo_url, default_branch, "
            "                            is_primary, created_at) "
            "VALUES (:id, :pid, 'primary', :rp, :ru, 'main', :pri, "
            "        CURRENT_TIMESTAMP)"
        ), {"id": uuid.uuid4().hex[:12], "pid": project_id,
            "rp": repo_path, "ru": repo_url, "pri": True})
    if rows:
        conn.commit()


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
            runtime_added |= _ensure_column(conn, "profiles", "mcp_strict", "BOOLEAN DEFAULT 0 NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "mcp_config_override", "TEXT")
            runtime_added |= _ensure_column(conn, "profiles", "env_vars", "TEXT")
            runtime_added |= _ensure_column(conn, "profiles", "home_path", "VARCHAR(500)")
            # AP-80 Conductor: opt-in autonomous task pickup
            runtime_added |= _ensure_column(conn, "profiles", "conductor_enabled", "BOOLEAN DEFAULT 0 NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "max_concurrent_runs", "INTEGER DEFAULT 1 NOT NULL")
            # System agents (Conductor, Concierge) + Conductor cadence config
            runtime_added |= _ensure_column(conn, "profiles", "is_system", "BOOLEAN DEFAULT 0 NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "conductor_tick_seconds", "INTEGER DEFAULT 60 NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "conductor_report_time", "VARCHAR(5) DEFAULT '09:00' NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "conductor_report_enabled", "BOOLEAN DEFAULT 1 NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "conductor_plan_interval_minutes", "INTEGER DEFAULT 10 NOT NULL")
            runtime_added |= _ensure_column(conn, "profiles", "conductor_active", "BOOLEAN DEFAULT 1 NOT NULL")
            # AP-155: agent-level sandbox containment mode.
            runtime_added |= _ensure_column(conn, "profiles", "sandbox_mode", "VARCHAR(20)")
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
            # AP-158: per-project gate-engine toggle.
            added |= _ensure_column(conn, "projects", "gates_enabled", "BOOLEAN DEFAULT 0 NOT NULL")
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
            _backfill_primary_project_repo(conn)
            if added:
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
