#!/usr/bin/env python3
"""
Migration: create/update tournament_categories, add entry_ranking_week and
seed_ranking_week to tournaments, and backfill both for all tournaments.

Safe to re-run: uses INSERT OR REPLACE and ALTER TABLE no-ops on existing columns.
"""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "tennis_fantasy.db"

ENTRY_DAYS_BEFORE = {
    "Grand Slam": 42,
    "ATP 1000":   28,
    "WTA 1000":   28,
    "ATP 500":    28,
    "WTA 500":    28,
    "ATP 250":    28,
    "WTA 250":    28,
}

SEED_DAYS_BEFORE = {
    "Grand Slam": 28,
    "ATP 1000":   14,
    "WTA 1000":   14,
    "ATP 500":    14,
    "WTA 500":    14,
    "ATP 250":    14,
    "WTA 250":    14,
}

QUAL_ENTRY_DAYS_BEFORE = {
    "Grand Slam": 28,
    "ATP 1000":   21,
    "WTA 1000":   21,
    "ATP 500":    21,
    "WTA 500":    21,
    "ATP 250":    21,
    "WTA 250":    21,
}

CATEGORY_SEED = [
    # (name, entry_days_before, qual_entry_days_before, seed_days_before, default_draw_size, alt_draw_size, logo_path)
    ("Grand Slam", 42, 28, 28, 128, None, None),
    ("ATP 1000",   28, 21, 14,  96,   64, None),
    ("WTA 1000",   28, 21, 14,  96,   64, None),
    ("ATP 500",    28, 21, 14,  32,   48, None),
    ("WTA 500",    28, 21, 14,  32,   56, None),
    ("ATP 250",    28, 21, 14,  28,   32, None),
    ("WTA 250",    28, 21, 14,  28,   32, None),
]


def compute_week(start_date_str, days_before):
    d = date.fromisoformat(start_date_str)
    monday = d - timedelta(days=d.weekday())
    return (monday - timedelta(days=days_before)).isoformat()


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Recreate tournament_categories with seed_days_before column
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tournament_categories (
            name TEXT PRIMARY KEY,
            entry_days_before INTEGER NOT NULL,
            qual_entry_days_before INTEGER NOT NULL,
            seed_days_before INTEGER NOT NULL DEFAULT 14,
            default_draw_size INTEGER NOT NULL,
            alt_draw_size INTEGER,
            logo_path TEXT
        )
    """)
    # Add seed_days_before column to existing table if not present
    try:
        cur.execute("ALTER TABLE tournament_categories ADD COLUMN seed_days_before INTEGER NOT NULL DEFAULT 14")
        print("Added seed_days_before column to tournament_categories.")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print("seed_days_before already exists in tournament_categories — skipping.")
        else:
            raise

    # 2. Upsert all category rows (includes seed_days_before values)
    cur.executemany(
        """
        INSERT OR REPLACE INTO tournament_categories
            (name, entry_days_before, qual_entry_days_before, seed_days_before,
             default_draw_size, alt_draw_size, logo_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        CATEGORY_SEED,
    )
    print(f"Upserted {len(CATEGORY_SEED)} category rows.")

    # 3. Add columns to tournaments (safe no-ops if already present)
    for col in ("entry_ranking_week DATE", "seed_ranking_week DATE"):
        col_name = col.split()[0]
        try:
            cur.execute(f"ALTER TABLE tournaments ADD COLUMN {col}")
            print(f"Added {col_name} column to tournaments.")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"{col_name} already exists — skipping.")
            else:
                raise

    # 4. Backfill both ranking weeks for all tournaments with start_date + category
    cur.execute(
        "SELECT id, start_date, category FROM tournaments "
        "WHERE start_date IS NOT NULL AND category IS NOT NULL"
    )
    rows = cur.fetchall()

    updated = skipped = 0
    for tid, start_date_str, category in rows:
        entry_days = ENTRY_DAYS_BEFORE.get(category)
        seed_days  = SEED_DAYS_BEFORE.get(category)
        if not entry_days or not seed_days:
            skipped += 1
            continue
        erw = compute_week(start_date_str, entry_days)
        srw = compute_week(start_date_str, seed_days)
        cur.execute(
            "UPDATE tournaments SET entry_ranking_week = ?, seed_ranking_week = ? WHERE id = ?",
            (erw, srw, tid),
        )
        updated += 1

    conn.commit()
    conn.close()
    print(f"Backfilled {updated} tournaments ({skipped} skipped — unknown category).")


if __name__ == "__main__":
    main()
