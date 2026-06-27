#!/usr/bin/env python3
"""
Migration: create tournament_categories table, add entry_ranking_week to tournaments,
and backfill entry_ranking_week for all tournaments that have start_date + category.
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
    # (name, entry_days_before, qual_entry_days_before, default_draw_size, alt_draw_size, logo_path)
    ("Grand Slam", 42, 28, 128, None, None),
    ("ATP 1000",   28, 21,  96,   64, None),
    ("WTA 1000",   28, 21,  96,   64, None),
    ("ATP 500",    28, 21,  32,   48, None),
    ("WTA 500",    28, 21,  32,   56, None),
    ("ATP 250",    28, 21,  28,   32, None),
    ("WTA 250",    28, 21,  28,   32, None),
]


def compute_entry_ranking_week(start_date_str: str, category: str):
    if not start_date_str or not category:
        return None
    days_before = ENTRY_DAYS_BEFORE.get(category)
    if days_before is None:
        return None
    start_date = date.fromisoformat(start_date_str)
    tournament_monday = start_date - timedelta(days=start_date.weekday())
    erw = tournament_monday - timedelta(days=days_before)
    return erw.isoformat()


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Create tournament_categories table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tournament_categories (
            name TEXT PRIMARY KEY,
            entry_days_before INTEGER NOT NULL,
            qual_entry_days_before INTEGER NOT NULL,
            default_draw_size INTEGER NOT NULL,
            alt_draw_size INTEGER,
            logo_path TEXT
        )
    """)
    print("Created tournament_categories table (or already existed).")

    # 2. Seed tournament_categories
    cur.executemany(
        """
        INSERT OR REPLACE INTO tournament_categories
            (name, entry_days_before, qual_entry_days_before, default_draw_size, alt_draw_size, logo_path)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        CATEGORY_SEED,
    )
    print(f"Seeded {len(CATEGORY_SEED)} category rows.")

    # 3. Add entry_ranking_week column to tournaments (safe no-op if already exists)
    try:
        cur.execute("ALTER TABLE tournaments ADD COLUMN entry_ranking_week DATE")
        print("Added entry_ranking_week column to tournaments.")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print("entry_ranking_week column already exists — skipping.")
        else:
            raise

    # 4. Backfill entry_ranking_week for all tournaments with start_date + category
    cur.execute("SELECT id, start_date, category FROM tournaments WHERE start_date IS NOT NULL AND category IS NOT NULL")
    rows = cur.fetchall()

    updated = 0
    skipped = 0
    for tid, start_date_str, category in rows:
        erw = compute_entry_ranking_week(start_date_str, category)
        if erw:
            cur.execute("UPDATE tournaments SET entry_ranking_week = ? WHERE id = ?", (erw, tid))
            updated += 1
        else:
            skipped += 1

    conn.commit()
    conn.close()
    print(f"Backfilled entry_ranking_week: {updated} updated, {skipped} skipped (unknown category).")


if __name__ == "__main__":
    main()
