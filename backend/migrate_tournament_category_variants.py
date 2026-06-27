#!/usr/bin/env python3
"""
Migration: extend tournament_categories with metadata fields, create
tournament_categories_variants, and backfill variant_id on tournaments.

Run inside the container:
  docker exec app-backend-1 python /tmp/migrate_tournament_category_variants.py

Safe to re-run: ALTER TABLE is a no-op on duplicate columns;
variant insert is skipped if rows already exist.
"""
import math
import sqlite3

DB_PATH = "/data/tennis_fantasy.db"

# ── New fields for tournament_categories ──────────────────────────────────────
# (name, sort_order, scoring_tier, unique_per_slot, one_per_slot, default_da_days, default_qual_days, wikipedia_url)
CATEGORY_META = [
    ("Grand Slam", 0, "GS",   1, 1, 3, 3, None),
    ("ATP 1000",   1, "1000", 1, 1, 5, 3, "https://en.wikipedia.org/wiki/ATP_Masters_1000_tournaments"),
    ("WTA 1000",   1, "1000", 1, 1, 5, 3, "https://en.wikipedia.org/wiki/WTA_1000_tournaments"),
    ("ATP 500",    2, "500",  1, 0, 4, 1, "https://en.wikipedia.org/wiki/ATP_500_tournaments"),
    ("WTA 500",    2, "500",  1, 0, 2, 1, "https://en.wikipedia.org/wiki/WTA_500_tournaments"),
    ("ATP 250",    3, "250",  0, 0, 2, 1, "https://en.wikipedia.org/wiki/ATP_250_tournaments"),
    ("WTA 250",    3, "250",  0, 0, 2, 1, "https://en.wikipedia.org/wiki/WTA_250_tournaments"),
]

# ── Variant seed data ─────────────────────────────────────────────────────────
# (category_name, draw_size, logo_path, is_default, label)
_VARIANTS_RAW = [
    # Grand Slam — one named variant per slam (for the logo), plus a fallback default
    ("Grand Slam", 128, "/logos/slams/slam_Australian.png",       False, "Australian Open"),
    ("Grand Slam", 128, "/logos/slams/slam_RolandGarros.svg.png", False, "French Open"),
    ("Grand Slam", 128, "/logos/slams/slam_Wimbledon.svg.png",    False, "Wimbledon"),
    ("Grand Slam", 128, "/logos/slams/slam_US.svg.png",           False, "US Open"),
    ("Grand Slam", 128, None,                                      True,  "Default"),
    # ATP 1000
    ("ATP 1000", 96, None, True,  "Standard 96"),   # Indian Wells/Miami/Madrid/Rome/Canada/Cincinnati/Shanghai
    ("ATP 1000", 56, None, False, "Paris/Monte-Carlo 56"),
    # ATP 500
    ("ATP 500", 32, None, True,  "Standard 32"),
    ("ATP 500", 48, None, False, "Washington 48"),
    # ATP 250
    ("ATP 250", 28, None, True,  "Standard 28"),
    ("ATP 250", 32, None, False, "Non-standard 32"),  # Brisbane, Geneva, Mallorca, Eastbourne, Munich
    ("ATP 250", 48, None, False, "Winston-Salem 48"),
    # WTA 1000
    ("WTA 1000", 96, None, True,  "Standard 96"),   # Indian Wells/Miami/Madrid/Rome/Canada/Cincinnati/China
    ("WTA 1000", 56, None, False, "Qatar/Dubai/Wuhan 56"),
    # WTA 500
    ("WTA 500", 28, None, True,  "Standard 28"),
    ("WTA 500", 30, None, False, "Adelaide 30"),
    ("WTA 500", 32, None, False, "Non-standard 32"),  # Bad Homburg, Singapore
    ("WTA 500", 48, None, False, "Charleston/Brisbane 48"),
    # WTA 250 — uniform 32-draw across all events
    ("WTA 250", 32, None, True,  "Standard 32"),
]


def _num_byes(draw_size: int) -> int:
    p = 1
    while p < draw_size:
        p <<= 1
    return p - draw_size


def _num_rounds(draw_size: int) -> int:
    return math.ceil(math.log2(draw_size))


VARIANTS = [
    (cat, ds, _num_byes(ds), _num_rounds(ds), logo, int(is_def), label)
    for cat, ds, logo, is_def, label in _VARIANTS_RAW
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Add new columns to tournament_categories
    print("--- tournament_categories ---")
    new_cols = [
        ("sort_order",        "INTEGER"),
        ("scoring_tier",      "TEXT"),
        ("unique_per_slot",   "INTEGER NOT NULL DEFAULT 0"),
        ("one_per_slot",      "INTEGER NOT NULL DEFAULT 0"),
        ("default_da_days",   "INTEGER"),
        ("default_qual_days", "INTEGER"),
        ("wikipedia_url",     "TEXT"),
    ]
    for col_name, col_def in new_cols:
        try:
            cur.execute(f"ALTER TABLE tournament_categories ADD COLUMN {col_name} {col_def}")
            print(f"  Added column: {col_name}")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                print(f"  Already exists: {col_name}")
            else:
                raise

    # 2. Update category rows
    for name, so, st, ups, ops, da, qa, wu in CATEGORY_META:
        cur.execute(
            """UPDATE tournament_categories SET
                sort_order=?, scoring_tier=?, unique_per_slot=?, one_per_slot=?,
                default_da_days=?, default_qual_days=?, wikipedia_url=?
               WHERE name=?""",
            (so, st, ups, ops, da, qa, wu, name),
        )
    print(f"  Updated {len(CATEGORY_META)} category rows with new fields")

    # 3. Create tournament_categories_variants
    print("\n--- tournament_categories_variants ---")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tournament_categories_variants (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT    NOT NULL REFERENCES tournament_categories(name),
            draw_size     INTEGER NOT NULL,
            num_byes      INTEGER NOT NULL,
            num_rounds    INTEGER NOT NULL,
            logo_path     TEXT,
            is_default    INTEGER NOT NULL DEFAULT 0,
            label         TEXT
        )
    """)
    print("  Table ensured")

    cur.execute("SELECT COUNT(*) FROM tournament_categories_variants")
    count = cur.fetchone()[0]
    if count == 0:
        cur.executemany(
            """INSERT INTO tournament_categories_variants
               (category_name, draw_size, num_byes, num_rounds, logo_path, is_default, label)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            VARIANTS,
        )
        print(f"  Inserted {len(VARIANTS)} variant rows")
    else:
        print(f"  Already populated ({count} rows) — skipping insert")

    # 4. Add variant_id to tournaments
    print("\n--- tournaments.variant_id ---")
    try:
        cur.execute(
            "ALTER TABLE tournaments ADD COLUMN variant_id INTEGER "
            "REFERENCES tournament_categories_variants(id)"
        )
        print("  Added column: variant_id")
    except Exception as e:
        if "duplicate column" in str(e).lower():
            print("  Already exists: variant_id")
        else:
            raise

    # 5. Build lookup tables
    cur.execute("SELECT id, category_name, draw_size, is_default, label FROM tournament_categories_variants")
    all_variants = cur.fetchall()

    # Grand Slam named variants: label → id
    slam_by_label = {v["label"]: v["id"] for v in all_variants if v["category_name"] == "Grand Slam"}
    slam_default_id = slam_by_label["Default"]

    # Non-GS: (category, draw_size) → id; prefer default when ambiguous
    non_slam: dict[tuple, int] = {}
    non_slam_default: dict[str, int] = {}
    for v in all_variants:
        if v["category_name"] == "Grand Slam":
            continue
        key = (v["category_name"], v["draw_size"])
        non_slam[key] = v["id"]
        if v["is_default"]:
            non_slam_default[v["category_name"]] = v["id"]

    # 6. Backfill variant_id for all tournaments where it is NULL
    cur.execute(
        "SELECT id, name, category, draw_size FROM tournaments WHERE variant_id IS NULL"
    )
    rows = cur.fetchall()

    updated = skipped = 0
    for row in rows:
        tid, tname, cat, ds = row["id"], row["name"], row["category"], row["draw_size"]
        if not cat:
            skipped += 1
            continue

        if cat == "Grand Slam":
            n = tname.lower()
            if "australian" in n:
                vid = slam_by_label.get("Australian Open", slam_default_id)
            elif "french" in n or "roland" in n:
                vid = slam_by_label.get("French Open", slam_default_id)
            elif "wimbledon" in n:
                vid = slam_by_label.get("Wimbledon", slam_default_id)
            elif "us open" in n:
                vid = slam_by_label.get("US Open", slam_default_id)
            else:
                vid = slam_default_id
        else:
            vid = non_slam.get((cat, ds)) or non_slam_default.get(cat)

        if vid:
            cur.execute("UPDATE tournaments SET variant_id=? WHERE id=?", (vid, tid))
            updated += 1
        else:
            skipped += 1

    conn.commit()
    conn.close()

    print(f"  Backfilled variant_id for {updated} tournaments ({skipped} skipped)")
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
