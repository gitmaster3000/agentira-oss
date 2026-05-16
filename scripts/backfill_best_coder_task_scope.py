"""ADR 008 migration: backfill best-coder run-scoped → task-scoped.

Only the best-coder agent is rewritten — other agents keep their existing
scope_keys because they had no production usage of run-scope worth
preserving. Per AP-93 user decision: "Can backfill. for best-coder only."

Idempotent: safe to re-run. Skips messages whose scope_key already starts
with 'task:'. Best-coder is identified by agent.name == 'best-coder'.

Effect:
  - forge_messages.scope_key: 'run:<run_id>' → 'task:<task_id>'
  - forge_conversations: rows with run-scope merged into task-scope rows
    (latest runtime_session_id wins so claude --resume keeps working on
    the most recent run)
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from backend.db import engine


def main() -> None:
    with engine.begin() as conn:
        agent = conn.execute(text(
            "SELECT id FROM forge_agents WHERE name = 'best-coder' LIMIT 1"
        )).first()
        if not agent:
            print("best-coder agent not found; nothing to migrate")
            return
        agent_id = agent[0]

        # Map every run_id → task_id (only runs that belong to best-coder
        # and have a task_id set).
        run_rows = conn.execute(text(
            "SELECT id, task_id FROM forge_runs "
            "WHERE agent_id = :aid AND task_id IS NOT NULL"
        ), {"aid": agent_id}).fetchall()
        run_to_task = {r[0]: r[1] for r in run_rows}
        print(f"Found {len(run_to_task)} best-coder runs with task_id")

        msg_updated = 0
        for rid, tid in run_to_task.items():
            res = conn.execute(text(
                "UPDATE forge_messages SET scope_key = :new "
                "WHERE agent_id = :aid AND scope_key = :old"
            ), {"new": f"task:{tid}", "old": f"run:{rid}", "aid": agent_id})
            msg_updated += res.rowcount or 0
        print(f"Rewrote {msg_updated} forge_messages.scope_key rows")

        # Conversations: collapse run-scoped rows into task-scoped, keeping
        # the most recently used session handle as the survivor.
        conv_merged = 0
        for rid, tid in run_to_task.items():
            old_scope = f"run:{rid}"
            new_scope = f"task:{tid}"
            old = conn.execute(text(
                "SELECT runtime_session_id, last_used_at FROM forge_conversations "
                "WHERE agent_id = :aid AND scope_key = :sk"
            ), {"aid": agent_id, "sk": old_scope}).first()
            if not old:
                continue
            existing = conn.execute(text(
                "SELECT last_used_at FROM forge_conversations "
                "WHERE agent_id = :aid AND scope_key = :sk"
            ), {"aid": agent_id, "sk": new_scope}).first()
            if existing and existing[0] and old[1] and existing[0] >= old[1]:
                # Task-scope row is newer; just drop the run-scope row.
                conn.execute(text(
                    "DELETE FROM forge_conversations "
                    "WHERE agent_id = :aid AND scope_key = :sk"
                ), {"aid": agent_id, "sk": old_scope})
            elif existing:
                # Run-scope row is newer; update task-scope row with its handle.
                conn.execute(text(
                    "UPDATE forge_conversations "
                    "SET runtime_session_id = :sid, last_used_at = :ts "
                    "WHERE agent_id = :aid AND scope_key = :sk"
                ), {"sid": old[0], "ts": old[1],
                    "aid": agent_id, "sk": new_scope})
                conn.execute(text(
                    "DELETE FROM forge_conversations "
                    "WHERE agent_id = :aid AND scope_key = :sk"
                ), {"aid": agent_id, "sk": old_scope})
            else:
                # No task-scope row yet; rename in place.
                conn.execute(text(
                    "UPDATE forge_conversations SET scope_key = :new "
                    "WHERE agent_id = :aid AND scope_key = :old"
                ), {"new": new_scope, "old": old_scope, "aid": agent_id})
            conv_merged += 1
        print(f"Merged {conv_merged} forge_conversations rows")


if __name__ == "__main__":
    main()
