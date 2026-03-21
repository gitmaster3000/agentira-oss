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
    from backend.forge.models import Agent, Run  # noqa: F401
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
