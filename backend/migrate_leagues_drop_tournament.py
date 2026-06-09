"""
One-time migration: remove tournament_id from the leagues table.
Leagues are now tournament-agnostic; the leaderboard is filtered per-tournament
based on which members have submitted predictions for that tournament.

Run with: python migrate_leagues_drop_tournament.py
"""
import sqlite3
import sys

DB_PATH = "tennis_fantasy.db"

DDL_NEW = """
CREATE TABLE leagues_new (
    id          INTEGER PRIMARY KEY,
    name        VARCHAR NOT NULL,
    owner_id    INTEGER NOT NULL REFERENCES users(id),
    scoring_mode VARCHAR NOT NULL DEFAULT 'classic',
    custom_points JSON,
    is_public   BOOLEAN NOT NULL DEFAULT 0,
    invite_code VARCHAR NOT NULL UNIQUE,
    created_at  DATETIME
)
"""

def migrate(db_path: str):
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # Check current schema
    cur.execute("PRAGMA table_info(leagues)")
    cols = [row[1] for row in cur.fetchall()]
    if "tournament_id" not in cols:
        print("tournament_id column not present — already migrated, nothing to do.")
        con.close()
        return

    print(f"Migrating {db_path}: dropping tournament_id from leagues …")
    cur.execute("PRAGMA foreign_keys = OFF")
    cur.execute("BEGIN TRANSACTION")
    try:
        cur.execute(DDL_NEW)
        cur.execute("""
            INSERT INTO leagues_new (id, name, owner_id, scoring_mode, custom_points, is_public, invite_code, created_at)
            SELECT                  id, name, owner_id, scoring_mode, custom_points, is_public, invite_code, created_at
            FROM leagues
        """)
        cur.execute("DROP TABLE leagues")
        cur.execute("ALTER TABLE leagues_new RENAME TO leagues")
        con.commit()
        print("Done.")
    except Exception as exc:
        con.rollback()
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        cur.execute("PRAGMA foreign_keys = ON")
        con.close()


if __name__ == "__main__":
    migrate(DB_PATH)
