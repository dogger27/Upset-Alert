"""How good is the win-probability model, on our own results?

    backend/.venv/bin/python scripts/winprob_calibration.py [path/to/db]

Scores every completed non-bye match in the database with `services.winprob`
and reports accuracy, log loss and Brier score against three alternatives, so
"is this model worth having" is a number rather than an opinion. Read-only.

    completed matches with both players: 4213
    elo+rank  n= 4213 accuracy=0.696  log-loss=0.5730  Brier=0.1950
    rank only n= 4213 accuracy=0.650  log-loss=0.6197  Brier=0.2159
    rank pick n= 4201 accuracy=0.651   (always the better-ranked player)

(dev snapshot, 2026-09-12: Elo is worth about five points of accuracy and
0.05 of log loss over the ranking, and the ranking alone is worth nothing at
all over simply backing the higher-ranked player.)

ONE BIAS TO KEEP IN MIND, and it flatters the model: the Elo it reads is the
LATEST week's, because that is what the live column reads. Scoring a match
from March with September's Elo knows a little about what happened in
between. Archive the weekly tables and re-run this per-match against the Elo
of that week for a clean number.
"""
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.winprob import predict   # noqa: E402


def best_of(nsets, gender, category):
    if nsets in (3, 5):
        return nsets
    return 5 if (gender == "M" and "Grand" in (category or "")) else 3


def main(db_path: str) -> None:
    c = sqlite3.connect(db_path)
    week = c.execute(
        "SELECT max(week_date) FROM te_rankings_snapshots WHERE elo IS NOT NULL").fetchone()[0]
    rows = c.execute("""
        SELECT d.gender, d.category, d.surface, d.sofa_number_of_sets,
               m.player1_id, m.winner_id, s1.elo, s2.elo, e1.ranking, e2.ranking
        FROM matches m
        JOIN draws d ON d.id = m.draw_id
        JOIN draw_entries e1 ON e1.id = m.player1_id
        JOIN draw_entries e2 ON e2.id = m.player2_id
        LEFT JOIN te_rankings_snapshots s1
               ON s1.player_id = e1.te_player_id AND s1.week_date = ?
        LEFT JOIN te_rankings_snapshots s2
               ON s2.player_id = e2.te_player_id AND s2.week_date = ?
        WHERE m.winner_id IS NOT NULL AND m.is_bye = 0
    """, (week, week)).fetchall()
    print(f"completed matches with both players: {len(rows)}  (Elo week {week})")

    for label, use_elo in (("elo+rank", True), ("rank only", False)):
        n = hit = 0
        ll = brier = 0.0
        for g, cat, surf, nsets, p1, w, e1, e2, r1, r2 in rows:
            ex, ey = (e1, e2) if use_elo else (None, None)
            if (ex is None or ey is None) and r1 is None and r2 is None:
                continue
            p = predict(rank_x=r1, rank_y=r2, elo_x=ex, elo_y=ey,
                        surface=surf, best_of=best_of(nsets, g, cat))["p"]
            y = 1 if w == p1 else 0
            n += 1
            ll -= math.log(max(1e-9, p if y else 1 - p))
            brier += (p - y) ** 2
            hit += (p >= 0.5) == bool(y)
        print(f"{label:9} n={n:5} accuracy={hit / n:.3f}  log-loss={ll / n:.4f}  Brier={brier / n:.4f}")

    n = hit = 0
    for g, cat, surf, nsets, p1, w, e1, e2, r1, r2 in rows:
        if r1 is None or r2 is None:
            continue
        n += 1
        hit += (r1 < r2) == (w == p1)
    print(f"{'rank pick':9} n={n:5} accuracy={hit / n:.3f}   (always the better-ranked player)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tennis_fantasy.db")
