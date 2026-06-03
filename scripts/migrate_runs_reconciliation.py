"""Idempotent migration for the Runs & Chats Reconciliation epic (AP-176..182).

Additive only — preserves all existing data:
  - new columns on forge_runs (is_work, interrupt_intent, last_heartbeat_at)
  - new columns on forge_conversations (rolling_summary, rolling_summary_through_run_id)
  - creates the forge_queued_messages table
  - remaps the old transient statuses (pausing/cancelling/resuming) onto the
    merged INTERRUPTING (+ intent) / PENDING
  - backfills is_work so previously-visible runs stay visible and old shadow
    rows fold into plain chat runs

Safe to run multiple times. Run inside the backend image against the live DB:

    docker run --rm -v "$PWD":/app -v agentira_agentira-data:/app/data \
        -w /app agentira-backend python scripts/migrate_runs_reconciliation.py
"""

from sqlalchemy import text

from backend.db import engine, Base
import backend.forge.models  # noqa: F401 — register tables for create_all


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def _add_column(conn, table: str, col: str, ddl: str) -> None:
    if col in _columns(conn, table):
        print(f"  = {table}.{col} (already present)")
        return
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
    print(f"  + {table}.{col}")


def main() -> None:
    print("Runs & Chats Reconciliation migration")

    print("\n[1/3] Adding columns…")
    with engine.begin() as conn:
        _add_column(conn, "forge_runs", "is_work", "BOOLEAN DEFAULT 0")
        _add_column(conn, "forge_runs", "interrupt_intent", "VARCHAR(10)")
        _add_column(conn, "forge_runs", "last_heartbeat_at", "DATETIME")
        _add_column(conn, "forge_conversations", "rolling_summary", "TEXT")
        _add_column(conn, "forge_conversations",
                    "rolling_summary_through_run_id", "VARCHAR(12)")

    print("\n[2/3] Creating new tables (forge_queued_messages)…")
    Base.metadata.create_all(engine)  # additive; existing tables untouched
    print("  done")

    print("\n[3/3] Remapping statuses + backfilling is_work…")
    with engine.begin() as conn:
        # Merge the transient trio into INTERRUPTING (+ intent) / PENDING.
        conn.execute(text(
            "UPDATE forge_runs SET interrupt_intent='pause' WHERE status='pausing'"))
        conn.execute(text(
            "UPDATE forge_runs SET interrupt_intent='discard' WHERE status='cancelling'"))
        conn.execute(text(
            "UPDATE forge_runs SET status='interrupting' "
            "WHERE status IN ('pausing','cancelling')"))
        conn.execute(text(
            "UPDATE forge_runs SET status='pending' WHERE status='resuming'"))

        # Backfill is_work. Everything that wasn't an un-promoted shadow was
        # already visible in the Runs list → keep it visible.
        conn.execute(text(
            "UPDATE forge_runs SET is_work=1 WHERE trigger_event != 'chat.shadow'"))
        # In-flight shadows at migration time: visible iff they produced work.
        conn.execute(text(
            "UPDATE forge_runs SET is_work = CASE WHEN "
            "((diff IS NOT NULL AND diff != '') "
            " OR (artifacts_json IS NOT NULL AND artifacts_json NOT IN ('','[]')) "
            " OR outcome IS NOT NULL) THEN 1 ELSE 0 END "
            "WHERE trigger_event='chat.shadow'"))
        # Fold the old magic trigger values into a plain 'chat' run.
        conn.execute(text(
            "UPDATE forge_runs SET trigger_event='chat' "
            "WHERE trigger_event IN ('chat.shadow','chat.work')"))
        # Safety: no NULL is_work.
        conn.execute(text(
            "UPDATE forge_runs SET is_work=0 WHERE is_work IS NULL"))

        n_runs = conn.execute(text("SELECT COUNT(*) FROM forge_runs")).scalar()
        n_work = conn.execute(
            text("SELECT COUNT(*) FROM forge_runs WHERE is_work=1")).scalar()
        print(f"  runs={n_runs}  is_work={n_work}")

    print("\n✓ migration complete")


if __name__ == "__main__":
    main()
