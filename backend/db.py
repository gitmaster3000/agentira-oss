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
    from backend.models import Project, Task, Activity, Epic, OAuthAccount  # noqa: F401
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
            if added:
                conn.commit()

        # OAuth accounts table — `create_all` makes this for us when
        # the model is registered, so we don't bootstrap it here anymore.

        # projects
        if "projects" in tables:
            if _ensure_column(conn, "projects", "webhook_config", "TEXT"):
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
            if added:
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
            if added:
                conn.commit()

        # forge_runs new columns
        if "forge_runs" in tables:
            added = False
            added |= _ensure_column(conn, "forge_runs", "session_id", "VARCHAR(80)")
            added |= _ensure_column(conn, "forge_runs", "workdir", "VARCHAR(500)")
            if added:
                conn.commit()

        # forge_runtimes new columns
        if "forge_runtimes" in tables:
            added = False
            added |= _ensure_column(conn, "forge_runtimes", "models", "TEXT")
            added |= _ensure_column(conn, "forge_runtimes", "gateway_url", "VARCHAR(500)")
            added |= _ensure_column(conn, "forge_runtimes", "gateway_token", "VARCHAR(500)")
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
