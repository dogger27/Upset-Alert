"""THE FINAL'S ACES AND MINUTES — what the tiebreak questions are asked against.

When a user enters a draw they are asked two things about the singles final
(owner, 2026-09-18): how many aces the champion will hit, and how long it
will last. Both answers break ties on points once the final is played. To
help them answer, the page shows the most useful figure we hold about the
player they have picked to win, and the slider runs from 0 to the most it
has ever been on this tour, in this format, on this surface.

Every number here comes from history.db's `tml_matches` — TennisMyLife's
copy of Sackmann's record, synced nightly — which carries `w_ace` / `l_ace`,
`minutes`, `score`, `surface`, `best_of` and `tourney_level` for close to
every tour match since 2023 (ATP 29.6k of 30.1k rows with aces; WTA 7.1k of
7.3k). Two rules shape the arithmetic:

- **The record has junk in it.** A 128-ace WTA best-of-three and a
  25-hour clay match are in the file. A ceiling is the largest PLAUSIBLE
  value: aces capped at 60 in a best-of-three and 120 in a best-of-five
  (Isner's 113 is real), minutes at 400 and 700 (Isner–Mahut's 665 is real).
- **Per SET, not per match.** A player's rate is aces divided by sets
  played, read off the score string, so a straight-sets win and a
  five-setter weigh what they should. A retirement counts the sets that were
  played; a walkover counts nothing.

All functions take an open sqlite3 connection and are run through
`history.db.run` by the callers; nothing here touches the event loop.
"""
import re
from datetime import date
from typing import Optional

# Levels that are the tour itself. 'C' is the Challenger tour, 'D' the team
# competitions; both are excluded from the ceilings and the tour baselines
# (a Challenger record is not "the most ever on the tour"), but a PLAYER's
# own rate reads every level, because that is where a qualifier's data is.
TOUR_LEVELS = {
    "atp": ("G", "M", "500", "250", "A", "F", "O"),
    "wta": ("G", "1000", "500", "250", "P", "PM", "I", "F", "W"),
}
PLAUSIBLE = {3: {"aces": 60, "minutes": 400}, 5: {"aces": 120, "minutes": 700}}
# How far back a player's or the tour's rate looks: three seasons.
SINCE_SEASONS = 3

_SET_RE = re.compile(r"^\d+-\d+(\(\d+\))?$|^\[\d+-\d+\]$")


def sets_in(score: Optional[str]) -> int:
    """Sets played, off a Sackmann score string: "6-2 6-4" is 2, "6-7(5) 7-6(3)
    7-5" is 3, "6-4 RET" is 1, "W/O" is 0. A match tiebreak "[10-8]" is a set."""
    return sum(1 for tok in (score or "").split() if _SET_RE.match(tok))


def _since(today: Optional[date] = None) -> str:
    y = (today or date.today()).year - (SINCE_SEASONS - 1)
    return f"{y}0101"


def _levels_sql(tour: str) -> str:
    return "(" + ",".join(f"'{lv}'" for lv in TOUR_LEVELS.get(tour, ())) + ")"


def ceilings(conn, tour: str, surface: str, best_of: int) -> dict:
    """The slider ends: the most aces one player has hit in a match on this
    tour in this format, and the longest a match has run on this surface in
    this format — the plausible maxima, with the match that set each."""
    cap = PLAUSIBLE.get(best_of, PLAUSIBLE[3])
    levels = _levels_sql(tour)
    row = conn.execute(f"""
        SELECT tourney_name, tourney_date, winner_name, loser_name, w_ace, l_ace, score
        FROM tml_matches
        WHERE tour = ? AND best_of = ? AND tourney_level IN {levels}
          AND max(coalesce(w_ace, 0), coalesce(l_ace, 0)) <= ?
        ORDER BY max(coalesce(w_ace, 0), coalesce(l_ace, 0)) DESC LIMIT 1""",
        (tour, best_of, cap["aces"])).fetchone()
    aces_max = max(row[4] or 0, row[5] or 0) if row else 0
    aces_rec = None
    if row:
        who = row[2] if (row[4] or 0) >= (row[5] or 0) else row[3]
        aces_rec = {"player": who, "aces": aces_max, "tournament": row[0],
                    "year": str(row[1])[:4], "score": row[6]}
    drow = conn.execute(f"""
        SELECT tourney_name, tourney_date, winner_name, loser_name, minutes, score
        FROM tml_matches
        WHERE tour = ? AND best_of = ? AND surface = ? AND tourney_level IN {levels}
          AND minutes IS NOT NULL AND minutes <= ?
        ORDER BY minutes DESC LIMIT 1""",
        (tour, best_of, surface, cap["minutes"])).fetchone()
    if not drow:
        drow = conn.execute(f"""
            SELECT tourney_name, tourney_date, winner_name, loser_name, minutes, score
            FROM tml_matches
            WHERE tour = ? AND best_of = ? AND tourney_level IN {levels}
              AND minutes IS NOT NULL AND minutes <= ?
            ORDER BY minutes DESC LIMIT 1""", (tour, best_of, cap["minutes"])).fetchone()
    duration_max = int(drow[4]) if drow else 0
    dur_rec = ({"players": f"{drow[2]} d. {drow[3]}", "minutes": duration_max,
                "tournament": drow[0], "year": str(drow[1])[:4], "score": drow[5]} if drow else None)
    return {"aces_max": int(aces_max), "aces_record": aces_rec,
            "duration_max_min": duration_max, "duration_record": dur_rec}


def _rate(rows) -> Optional[dict]:
    """{aces_per_set, minutes_per_set, matches, sets} over (aces, minutes, score) rows."""
    aces = sets_a = mins = sets_m = n = 0
    for a, m, score in rows:
        s = sets_in(score)
        if not s:
            continue
        n += 1
        if a is not None:
            aces += a
            sets_a += s
        if m is not None and m > 0:
            mins += m
            sets_m += s
    if not n:
        return None
    return {"matches": n,
            "aces_per_set": round(aces / sets_a, 2) if sets_a else None,
            "minutes_per_set": round(mins / sets_m, 1) if sets_m else None}


def player_reference(conn, tour: str, tml_id: str, surface: str,
                     opponent_tml_id: Optional[str] = None, today: Optional[date] = None) -> dict:
    """The picked champion's own rates: on this surface over the last three
    seasons, and against the picked runner-up whenever they have met."""
    since = _since(today)
    q = """
        SELECT CASE WHEN winner_id = :p THEN w_ace ELSE l_ace END, minutes, score
        FROM tml_matches
        WHERE tour = :tour AND (winner_id = :p OR loser_id = :p) AND tourney_date >= :since
          AND score NOT LIKE '%W/O%'"""
    on_surface = _rate(conn.execute(q + " AND surface = :surface",
                                    {"p": tml_id, "tour": tour, "since": since, "surface": surface}).fetchall())
    overall = _rate(conn.execute(q, {"p": tml_id, "tour": tour, "since": since}).fetchall())
    vs = None
    if opponent_tml_id:
        vs = _rate(conn.execute("""
            SELECT CASE WHEN winner_id = :p THEN w_ace ELSE l_ace END, minutes, score
            FROM tml_matches
            WHERE tour = :tour AND ((winner_id = :p AND loser_id = :o) OR (winner_id = :o AND loser_id = :p))
              AND score NOT LIKE '%W/O%'""", {"p": tml_id, "o": opponent_tml_id, "tour": tour}).fetchall())
    return {"on_surface": on_surface, "overall": overall, "vs_finalist": vs}


def tour_reference(conn, tour: str, surface: str, today: Optional[date] = None) -> Optional[dict]:
    """The tour's own rate on this surface: aces per set per PLAYER (each
    match counts both players' aces over the sets played), minutes per set."""
    since = _since(today)
    levels = _levels_sql(tour)
    rows = conn.execute(f"""
        SELECT w_ace, l_ace, minutes, score FROM tml_matches
        WHERE tour = ? AND surface = ? AND tourney_date >= ? AND tourney_level IN {levels}
          AND score NOT LIKE '%W/O%'""", (tour, surface, since)).fetchall()
    aces = sets_a = mins = sets_m = n = 0
    for wa, la, m, score in rows:
        s = sets_in(score)
        if not s:
            continue
        n += 1
        if wa is not None and la is not None:
            aces += wa + la
            sets_a += 2 * s
        if m is not None and m > 0:
            mins += m
            sets_m += s
    if not n:
        return None
    return {"matches": n,
            "aces_per_set": round(aces / sets_a, 2) if sets_a else None,
            "minutes_per_set": round(mins / sets_m, 1) if sets_m else None}


def default_guess(conn, tour: str, surface: str, best_of: int,
                  today: Optional[date] = None) -> Optional[dict]:
    """WHAT A BRACKET THAT NEVER ANSWERS IS TAKEN TO HAVE SAID (owner,
    2026-09-18): last year's average, for this gender, on this surface, in
    this format — the winner's aces in a match, and the match's length.

    PER MATCH, not per set: the question is how many aces the champion hits
    in the final and how long the final lasts, so the default has to be an
    answer to those questions and not a rate. The previous CALENDAR year, so
    every bracket in a season is defaulted against the same settled sample
    rather than a window that slides under them. Tour levels only, and the
    same plausibility caps as the ceilings, since the file holds junk.
    """
    year = (today or date.today()).year - 1
    cap = PLAUSIBLE.get(best_of, PLAUSIBLE[3])
    levels = _levels_sql(tour)
    row = conn.execute(f"""
        SELECT avg(w_ace), avg(minutes), count(*)
        FROM tml_matches
        WHERE tour = ? AND surface = ? AND best_of = ? AND tourney_level IN {levels}
          AND tourney_date >= ? AND tourney_date <= ?
          AND score NOT LIKE '%W/O%'
          AND w_ace IS NOT NULL AND w_ace <= ?
          AND minutes IS NOT NULL AND minutes > 0 AND minutes <= ?""",
        (tour, surface, best_of, f"{year}0101", f"{year}1231", cap["aces"], cap["minutes"])).fetchone()
    if not row or not row[2]:
        return None
    return {"aces": int(round(row[0])), "minutes": int(round(row[1])),
            "matches": int(row[2]), "year": year}
