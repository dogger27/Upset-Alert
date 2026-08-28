"""Merge orphaned blank qualifier entries into the named entry at the same slot.

A bracket position held two rows: a placeholder created before the qualifier was
known, and the named row the scraper later inserted instead of renaming the
placeholder. Predictions kept pointing at the placeholder, so those picks named
nobody in the match and would have scored nothing — and the blank rows also made
the draw look half-transcribed, which held the qualifiers-added announcement.

The two rows ARE the same slot, so re-pointing a pick is not a guess about what
the user meant: the placeholder they chose became that player.
"""
import sqlite3

DB = "/data/tennis_fantasy.db"

c = sqlite3.connect(DB)
pairs = c.execute("""
    SELECT draw_id, bracket_position,
           min(CASE WHEN trim(coalesce(name,'')) =  '' THEN id END) AS blank,
           min(CASE WHEN trim(coalesce(name,'')) <> '' THEN id END) AS named
      FROM draw_entries
     WHERE bracket_position IS NOT NULL
     GROUP BY draw_id, bracket_position
    HAVING count(*) > 1
""").fetchall()

moved = deleted = skipped = 0
for draw_id, pos, blank, named in pairs:
    if blank is None or named is None:
        print(f"  SKIP draw {draw_id} pos {pos}: not a blank/named pair")
        skipped += 1
        continue
    # A match must never point at the row about to go.
    refs = c.execute("SELECT count(*) FROM matches WHERE player1_id=? OR player2_id=? OR winner_id=?",
                     (blank, blank, blank)).fetchone()[0]
    if refs:
        print(f"  SKIP draw {draw_id} pos {pos}: {refs} match rows still reference {blank}")
        skipped += 1
        continue
    n = c.execute("UPDATE user_predictions SET predicted_winner_id=? WHERE predicted_winner_id=?",
                  (named, blank)).rowcount
    c.execute("UPDATE draw_change_events SET entry_id=? WHERE entry_id=?", (named, blank))
    c.execute("UPDATE schedule_entry_players SET draw_entry_id=? WHERE draw_entry_id=?", (named, blank))
    c.execute("DELETE FROM draw_entries WHERE id=?", (blank,))
    moved += n
    deleted += 1
    print(f"  draw {draw_id} pos {pos}: {blank} -> {named}, {n} pick(s) re-pointed")

c.commit()
print(f"\nre-pointed {moved} picks, removed {deleted} orphan entries, skipped {skipped}")

dup = c.execute("""SELECT count(*) FROM (SELECT draw_id, bracket_position FROM draw_entries
                   WHERE bracket_position IS NOT NULL GROUP BY 1,2 HAVING count(*)>1)""").fetchone()[0]
dang = c.execute("""SELECT count(*) FROM user_predictions p
                      JOIN matches m ON m.id = p.match_id
                      JOIN draw_entries e ON e.id = p.predicted_winner_id
                     WHERE trim(coalesce(e.name,'')) = ''
                       AND m.player1_id IS NOT NULL AND m.player2_id IS NOT NULL
                       AND p.predicted_winner_id NOT IN (m.player1_id, m.player2_id)""").fetchone()[0]
print(f"duplicate bracket positions remaining: {dup}")
print(f"placeholder picks still dangling:      {dang}")
for d in (77, 78):
    n = c.execute("SELECT count(*) FROM draw_entries WHERE draw_id=? AND trim(coalesce(name,''))=''",
                  (d,)).fetchone()[0]
    print(f"  draw {d}: {n} un-named entries left")
