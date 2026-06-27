#!/usr/bin/env python3
"""
Migration: rename tables and FK columns to match the new draws hierarchy.

Before:  tournaments, tournament_categories, tournament_categories_variants
After:   draws, draw_categories, draw_category_variants

Also:
  - Creates new `tournaments` table (event-level: name, year, city, country, surface)
  - Populates it from `draws` (one row per unique name+year combination)
  - Adds draws.tournament_id FK → tournaments.id and backfills it
  - Renames tournament_id → draw_id in draw_entries, matches,
    user_predictions, tournament_results

Run locally:
  python backend/migrate_draws_rename.py

Run in container:
  docker exec app-backend-1 python /tmp/migrate_draws_rename.py
"""

import sqlite3

DB_PATH = "backend/tennis_fantasy.db"   # local path; change to /data/tennis_fantasy.db in container


def col_exists(cur, table, col):
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())


def table_exists(cur, name):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = OFF")

    # ── 1. Rename tables ──────────────────────────────────────────────────────
    print("--- Renaming tables ---")

    if table_exists(cur, "tournaments") and not table_exists(cur, "draws"):
        cur.execute("ALTER TABLE tournaments RENAME TO draws")
        print("  tournaments → draws")
    elif table_exists(cur, "draws"):
        print("  draws already exists — skipping rename")

    if table_exists(cur, "tournament_categories") and not table_exists(cur, "draw_categories"):
        cur.execute("ALTER TABLE tournament_categories RENAME TO draw_categories")
        print("  tournament_categories → draw_categories")
    elif table_exists(cur, "draw_categories"):
        print("  draw_categories already exists — skipping rename")

    if table_exists(cur, "tournament_categories_variants") and not table_exists(cur, "draw_category_variants"):
        cur.execute("ALTER TABLE tournament_categories_variants RENAME TO draw_category_variants")
        print("  tournament_categories_variants → draw_category_variants")
    elif table_exists(cur, "draw_category_variants"):
        print("  draw_category_variants already exists — skipping rename")

    # ── 2. Rename tournament_id → draw_id in dependent tables ─────────────────
    print("\n--- Renaming FK columns ---")

    for table in ("draw_entries", "matches", "user_predictions", "tournament_results"):
        if not table_exists(cur, table):
            print(f"  {table}: table not found, skipping")
            continue
        if col_exists(cur, table, "tournament_id") and not col_exists(cur, table, "draw_id"):
            cur.execute(f"ALTER TABLE {table} RENAME COLUMN tournament_id TO draw_id")
            print(f"  {table}.tournament_id → draw_id")
        elif col_exists(cur, table, "draw_id"):
            print(f"  {table}.draw_id already exists — skipping")

    # ── 3. Create new tournaments table (event-level) ─────────────────────────
    print("\n--- Creating tournaments (event) table ---")

    if not table_exists(cur, "tournaments"):
        cur.execute("""
            CREATE TABLE tournaments (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                year       INTEGER NOT NULL,
                city       TEXT,
                country    TEXT,
                surface    TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("  Created tournaments table")
    else:
        print("  tournaments table already exists — skipping")

    # ── 4. Populate tournaments from draws ────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM tournaments")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO tournaments (name, year, city, country, surface)
            SELECT DISTINCT name, year, city, country, surface
            FROM draws
            ORDER BY year, name
        """)
        n = cur.rowcount
        print(f"  Inserted {n} tournament (event) rows")
    else:
        print("  tournaments already populated — skipping")

    # ── 5. Add tournament_id to draws and backfill ────────────────────────────
    print("\n--- Adding draws.tournament_id ---")

    if not col_exists(cur, "draws", "tournament_id"):
        cur.execute("ALTER TABLE draws ADD COLUMN tournament_id INTEGER REFERENCES tournaments(id)")
        print("  Added draws.tournament_id")
    else:
        print("  draws.tournament_id already exists — skipping")

    cur.execute("SELECT COUNT(*) FROM draws WHERE tournament_id IS NULL")
    if cur.fetchone()[0] > 0:
        cur.execute("""
            UPDATE draws SET tournament_id = (
                SELECT t.id FROM tournaments t
                WHERE t.name = draws.name AND t.year = draws.year
                LIMIT 1
            )
            WHERE tournament_id IS NULL
        """)
        print(f"  Backfilled {cur.rowcount} draws.tournament_id values")
    else:
        print("  draws.tournament_id already backfilled — skipping")

    conn.commit()
    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
