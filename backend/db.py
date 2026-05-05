"""Database engine and session management."""

import os
from pathlib import Path
from sqlalchemy import create_engine
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


def run_migrations():
    """Apply incremental schema changes to existing SQLite databases.
    Postgres gets the full schema from create_all() so migrations are skipped."""
    if not _is_sqlite:
        return
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(activities)"))
        existing = {row[1] for row in result}
        if "diff" not in existing:
            conn.execute(text("ALTER TABLE activities ADD COLUMN diff TEXT"))
            conn.commit()

        result = conn.execute(text("PRAGMA table_info(profiles)"))
        existing = {row[1] for row in result}
        if "webhook_url" not in existing:
            conn.execute(text("ALTER TABLE profiles ADD COLUMN webhook_url VARCHAR(500) DEFAULT ''"))
            conn.commit()
        if "notification_transport" not in existing:
            conn.execute(text("ALTER TABLE profiles ADD COLUMN notification_transport VARCHAR(20)"))
            conn.commit()
        if "email" not in existing:
            conn.execute(text("ALTER TABLE profiles ADD COLUMN email VARCHAR(255)"))
            conn.commit()

        # OAuth accounts table
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "oauth_accounts" not in tables:
            conn.execute(text("""
                CREATE TABLE oauth_accounts (
                    id VARCHAR(12) PRIMARY KEY,
                    profile_id VARCHAR(12) NOT NULL REFERENCES profiles(id),
                    provider VARCHAR(30) NOT NULL,
                    provider_user_id VARCHAR(255) NOT NULL,
                    created_at DATETIME,
                    UNIQUE(provider, provider_user_id)
                )
            """))
            conn.commit()

        result = conn.execute(text("PRAGMA table_info(projects)"))
        existing = {row[1] for row in result}
        if "webhook_config" not in existing:
            conn.execute(text("ALTER TABLE projects ADD COLUMN webhook_config TEXT"))
            conn.commit()

        # DOD items on tasks
        result = conn.execute(text("PRAGMA table_info(tasks)"))
        existing = {row[1] for row in result}
        if "dod_items" not in existing:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN dod_items TEXT"))
            conn.commit()
        if "branch" not in existing:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN branch VARCHAR(255) DEFAULT ''"))
            conn.commit()
        if "pr_url" not in existing:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN pr_url VARCHAR(500) DEFAULT ''"))
            conn.commit()
        if "start_date" not in existing:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN start_date DATETIME"))
            conn.commit()
        if "due_date" not in existing:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN due_date DATETIME"))
            conn.commit()
        if "epic_id" not in existing:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN epic_id VARCHAR(12) REFERENCES epics(id)"))
            conn.commit()

        # forge_runtimes table
        if "forge_runtimes" not in tables:
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
        result = conn.execute(text("PRAGMA table_info(forge_agents)"))
        existing = {row[1] for row in result}
        if "runtime_id" not in existing:
            conn.execute(text("ALTER TABLE forge_agents ADD COLUMN runtime_id VARCHAR(12) REFERENCES forge_runtimes(id)"))
            conn.commit()
        if "schedule_cron" not in existing:
            conn.execute(text("ALTER TABLE forge_agents ADD COLUMN schedule_cron VARCHAR(60)"))
            conn.commit()

        # forge_runs new columns
        result = conn.execute(text("PRAGMA table_info(forge_runs)"))
        existing = {row[1] for row in result}
        if "session_id" not in existing:
            conn.execute(text("ALTER TABLE forge_runs ADD COLUMN session_id VARCHAR(80)"))
            conn.commit()
        if "workdir" not in existing:
            conn.execute(text("ALTER TABLE forge_runs ADD COLUMN workdir VARCHAR(500)"))
            conn.commit()

        # forge_runtimes new columns
        result = conn.execute(text("PRAGMA table_info(forge_runtimes)"))
        existing = {row[1] for row in result}
        if "models" not in existing:
            conn.execute(text("ALTER TABLE forge_runtimes ADD COLUMN models TEXT"))
            conn.commit()
        if "gateway_url" not in existing:
            conn.execute(text("ALTER TABLE forge_runtimes ADD COLUMN gateway_url VARCHAR(500)"))
            conn.commit()
        if "gateway_token" not in existing:
            conn.execute(text("ALTER TABLE forge_runtimes ADD COLUMN gateway_token VARCHAR(500)"))
            conn.commit()

        # forge_agents.profile_id NOT NULL → NULLABLE rebuild
        # (agents are runtime executors; profile FK is legacy and now optional)
        if "forge_agents" in tables:
            cols = list(conn.execute(text("PRAGMA table_info(forge_agents)")))
            pid_col = next((c for c in cols if c[1] == "profile_id"), None)
            if pid_col and pid_col[3] == 1:  # notnull == 1
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
                conn.commit()
