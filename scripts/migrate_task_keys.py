"""Migration: Add Jira-style task keys.

Adds:
  - projects.key_prefix  VARCHAR(10)
  - projects.next_task_number  INTEGER
  - tasks.key  VARCHAR(20) UNIQUE

Then backfills existing projects with a derived prefix and assigns keys to all existing tasks.
"""

import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from backend.db import engine


def derive_prefix(name: str) -> str:
    """Derive a short uppercase prefix from a project name.

    Examples: 'Agentira' -> 'AGNT', 'My Cool Project' -> 'MCP', 'demo' -> 'DEMO'
    """
    words = re.findall(r'[A-Za-z]+', name)
    if not words:
        return "PROJ"
    if len(words) == 1:
        w = words[0].upper()
        # Take consonants, fallback to first 4 chars
        consonants = re.sub(r'[AEIOU]', '', w)
        return (consonants[:4] if len(consonants) >= 3 else w[:4]).ljust(2, 'X')
    # Multiple words: take first letter of each, up to 5
    return ''.join(w[0].upper() for w in words[:5])


def run():
    with engine.connect() as conn:
        # -- Add columns if missing --
        result = conn.execute(text("PRAGMA table_info(projects)"))
        proj_cols = {row[1] for row in result}

        if "key_prefix" not in proj_cols:
            conn.execute(text("ALTER TABLE projects ADD COLUMN key_prefix VARCHAR(10) DEFAULT 'PROJ'"))
            print("Added projects.key_prefix")

        if "next_task_number" not in proj_cols:
            conn.execute(text("ALTER TABLE projects ADD COLUMN next_task_number INTEGER DEFAULT 1"))
            print("Added projects.next_task_number")

        result = conn.execute(text("PRAGMA table_info(tasks)"))
        task_cols = {row[1] for row in result}

        if "key" not in task_cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN 'key' VARCHAR(20)"))
            print("Added tasks.key")

        conn.commit()

        # -- Backfill project prefixes --
        projects = conn.execute(text(
            "SELECT id, name, key_prefix FROM projects"
        )).fetchall()

        used_prefixes = set()
        for pid, pname, existing_prefix in projects:
            if existing_prefix and existing_prefix != "PROJ":
                used_prefixes.add(existing_prefix)
                continue
            prefix = derive_prefix(pname)
            # Deduplicate
            base = prefix
            i = 2
            while prefix in used_prefixes:
                prefix = f"{base}{i}"
                i += 1
            used_prefixes.add(prefix)
            conn.execute(text("UPDATE projects SET key_prefix = :prefix WHERE id = :pid"),
                         {"prefix": prefix, "pid": pid})
            print(f"  Project '{pname}' -> prefix '{prefix}'")

        conn.commit()

        # -- Backfill task keys --
        for pid, pname, _ in projects:
            row = conn.execute(text(
                "SELECT key_prefix FROM projects WHERE id = :pid"
            ), {"pid": pid}).fetchone()
            prefix = row[0]

            tasks = conn.execute(text(
                "SELECT id FROM tasks WHERE project_id = :pid AND (key IS NULL OR key = '') ORDER BY created_at ASC"
            ), {"pid": pid}).fetchall()

            if not tasks:
                continue

            # Find current max number for this prefix
            existing_max = conn.execute(text(
                "SELECT MAX(CAST(SUBSTR(key, :offset) AS INTEGER)) FROM tasks WHERE key LIKE :pattern"
            ), {"offset": len(prefix) + 2, "pattern": f"{prefix}-%"}).fetchone()[0] or 0

            num = existing_max + 1
            for (tid,) in tasks:
                key = f"{prefix}-{num}"
                conn.execute(text("UPDATE tasks SET key = :key WHERE id = :tid"),
                             {"key": key, "tid": tid})
                num += 1

            conn.execute(text("UPDATE projects SET next_task_number = :num WHERE id = :pid"),
                         {"num": num, "pid": pid})
            print(f"  Assigned keys {prefix}-{existing_max + 1} to {prefix}-{num - 1} ({len(tasks)} tasks)")

        conn.commit()

        # Create unique index on key (after backfill)
        try:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_tasks_key ON tasks('key')"))
            conn.commit()
            print("Created unique index on tasks.key")
        except Exception as e:
            print(f"Index creation skipped (may already exist): {e}")

        print("Migration complete.")


if __name__ == "__main__":
    run()
