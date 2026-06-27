"""One-off migration: rename surface 'Indoor' -> 'Hard' in h2h_cache.data_json."""
import json
import sqlite3
import sys

db_path = sys.argv[1] if len(sys.argv) > 1 else "tennis_fantasy.db"

conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT slug_a, slug_b, data_json FROM h2h_cache")
rows = cur.fetchall()

updated = 0
for slug_a, slug_b, data_raw in rows:
    data = json.loads(data_raw)
    dirty = False

    for match in data.get("matches", []):
        if match.get("surface") in ("Indoor", "Indoors"):
            match["surface"] = "Hard"
            dirty = True

    sw = data.get("surface_wins", {})
    for key in ("Indoor", "Indoors"):
        if key in sw:
            existing = sw.get("Hard", [0, 0])
            indoor = sw.pop(key)
            sw["Hard"] = [existing[0] + indoor[0], existing[1] + indoor[1]]
            dirty = True

    if dirty:
        cur.execute(
            "UPDATE h2h_cache SET data_json = ? WHERE slug_a = ? AND slug_b = ?",
            (json.dumps(data), slug_a, slug_b),
        )
        updated += 1

conn.commit()
conn.close()
print(f"Updated {updated} rows in {db_path}")
