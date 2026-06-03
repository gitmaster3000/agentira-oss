"""Add Project.wake_on_comment (AP-184). Idempotent, additive.

    docker run --rm -v "$PWD":/app -v agentira_agentira-data:/app/data \
        -w /app agentira-backend python scripts/migrate_comment_wake.py
"""

from sqlalchemy import text

from backend.db import engine
import backend.models  # noqa: F401 — register tables


def main() -> None:
    with engine.begin() as conn:
        cols = {r[1] for r in
                conn.execute(text("PRAGMA table_info(projects)")).fetchall()}
        if "wake_on_comment" in cols:
            print("= projects.wake_on_comment (already present)")
        else:
            conn.execute(text(
                "ALTER TABLE projects ADD COLUMN wake_on_comment "
                "BOOLEAN DEFAULT 0 NOT NULL"))
            print("+ projects.wake_on_comment")
    print("✓ done")


if __name__ == "__main__":
    main()
