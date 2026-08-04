"""
One-off migration: add tenant_id to hospitals/doctors so the same DB can serve
multiple hospital brands. Existing rows backfill to 'gleneagles'.

Run once: python -m src.workflows.data.migrate_add_tenant
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "db" / "knowledge_base.db"


def _has_column(cur: sqlite3.Cursor, table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def migrate() -> None:
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()

        for table in ("hospitals", "doctors"):
            if not _has_column(cur, table, "tenant_id"):
                cur.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id VARCHAR")
                print(f"Added tenant_id column to {table}")
            else:
                print(f"{table}.tenant_id already exists")

            cur.execute(
                f"UPDATE {table} SET tenant_id = 'gleneagles' WHERE tenant_id IS NULL"
            )
            print(f"Backfilled {cur.rowcount} row(s) in {table}")

        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    migrate()
