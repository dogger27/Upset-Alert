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
    """The window's first day, as `tml_matches.tourney_date` actually spells a
    date: DASHED ISO, "2024-01-01".

    Every one of the 494,876 rows is dashed, though Sackmann's own files are
    YYYYMMDD — our loader normalises them. A compact bound silently half
    worked and was worse than failing: "2025-03-10" >= "20250101" compares
    the fifth characters, "-" against "0", and is FALSE, so a bound of
    20250101 dropped all of 2025 while a bound of 20230101 kept 2024 onward
    and dropped 2023. The default came back empty and the per-set rates were
    quietly short a season (2026-09-18).
    """
    y = (today or date.today()).year - (SINCE_SEASONS - 1)
    return f"{y}-01-01"


def _levels_sql(tour: str) -> str:
    return "(" + ",".join(f"'{lv}'" for lv in TOUR_LEVELS.get(tour, ())) + ")"


def _year_ago(today: Optional[date] = None) -> str:
    """A year back from today, dashed ISO — the window the slider ends read.

    See feedback_history_db_dates_are_dashed: a compact bound here would half
    work and silently drop a season.
    """
    d = today or date.today()
    try:
        return d.replace(year=d.year - 1).isoformat()
    except ValueError:                      # 29 February
        return d.replace(year=d.year - 1, day=28).isoformat()


def ceilings(conn, tour: str, surface: str, best_of: int,
             today: Optional[date] = None) -> dict:
    """The slider ends: the most aces one player has hit in a match on this
    tour in this format, and the longest a match has run on this surface in
    this format — the plausible maxima, with the match that set each.

    THE PAST YEAR, NOT ALL TIME (owner, 2026-09-19). All-time ends were both
    stale and useless as a scale: the WTA best-of-three aces record is
    Pliskova's 31 from the 2016 Australian Open, and the longest hard-court
    match ran 5h 16m, so the answers anybody actually gives — a couple of aces,
    an hour and a half — lived in the first third of each track. A year of the
    same tour and format puts the whole slider inside reachable numbers while
    still being a real match somebody played.

    The window can be empty (a tour and format with no matches yet this year),
    and a ceiling of zero is a slider with no range, so each end falls back to
    all time rather than breaking the control.
    """
    cap = PLAUSIBLE.get(best_of, PLAUSIBLE[3])
    levels = _levels_sql(tour)
    since = _year_ago(today)

    def newest_first(sql: str, params: tuple):
        """The windowed answer if the year has one, else all time."""
        row = conn.execute(sql.format(window="AND tourney_date >= ?"),
                           params + (since,)).fetchone()
        return row or conn.execute(sql.format(window=""), params).fetchone()

    ace_sql = f"""
        SELECT tourney_name, tourney_date, winner_name, loser_name, w_ace, l_ace, score
        FROM tml_matches
        WHERE tour = ? AND best_of = ? AND tourney_level IN {levels}
          AND max(coalesce(w_ace, 0), coalesce(l_ace, 0)) <= ?
          {{window}}
        ORDER BY max(coalesce(w_ace, 0), coalesce(l_ace, 0)) DESC LIMIT 1"""
    row = newest_first(ace_sql, (tour, best_of, cap["aces"]))
    aces_max = max(row[4] or 0, row[5] or 0) if row else 0
    aces_rec = None
    if row:
        who = row[2] if (row[4] or 0) >= (row[5] or 0) else row[3]
        aces_rec = {"player": who, "aces": aces_max, "tournament": row[0],
                    "year": str(row[1])[:4], "score": row[6]}

    dur_sql = f"""
        SELECT tourney_name, tourney_date, winner_name, loser_name, minutes, score
        FROM tml_matches
        WHERE tour = ? AND best_of = ? AND surface = ? AND tourney_level IN {levels}
          AND minutes IS NOT NULL AND minutes <= ?
          {{window}}
        ORDER BY minutes DESC LIMIT 1"""
    drow = newest_first(dur_sql, (tour, best_of, surface, cap["minutes"]))
    if not drow:
        # No match on this surface at all: the format's own longest, so the
        # track still has a sane end.
        any_surface = f"""
            SELECT tourney_name, tourney_date, winner_name, loser_name, minutes, score
            FROM tml_matches
            WHERE tour = ? AND best_of = ? AND tourney_level IN {levels}
              AND minutes IS NOT NULL AND minutes <= ?
              {{window}}
            ORDER BY minutes DESC LIMIT 1"""
        drow = newest_first(any_surface, (tour, best_of, cap["minutes"]))
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


def head_to_head(conn, tour: str, tml_id: str, opponent_tml_id: str,
                 limit: int = 12) -> Optional[dict]:
    """THE MEETINGS THEMSELVES (owner, 2026-09-19): every match we hold between
    the two players this bracket has picked for the final, each with its score,
    its length, and the aces EACH of them hit — not just the per-set rate the
    reference lines carry.

    All-time, not the three-season window the rates use: a head-to-head is a
    short list and its oldest entry is still the answer to "have they played".
    Most recent first, capped at `limit` with the full count returned beside
    it, because a pair can have met thirty times and this goes in a drawer.

    Walkovers are left out. A W/O is a meeting in the record but not a match
    anybody hit an ace in, so every column this exists to show would be blank —
    and it is the same exclusion `_rate` makes, which keeps the list's length
    and the reference line's match count from contradicting each other.
    """
    if not tml_id or not opponent_tml_id:
        return None
    rows = conn.execute("""
        SELECT tourney_date, tourney_name, surface, round, score, minutes, best_of,
               winner_id, winner_name, loser_name, w_ace, l_ace
        FROM tml_matches
        WHERE tour = :tour
          AND ((winner_id = :p AND loser_id = :o) OR (winner_id = :o AND loser_id = :p))
          AND score NOT LIKE '%W/O%'
        ORDER BY tourney_date DESC""",
        {"p": tml_id, "o": opponent_tml_id, "tour": tour}).fetchall()
    if not rows:
        return None
    out = []
    for r in rows[:limit]:
        (tdate, tname, surf, rnd, score, minutes, best_of, wid, wname, lname, w_ace, l_ace) = r
        mine_won = wid == tml_id
        out.append({
            "date": tdate, "year": str(tdate)[:4], "tournament": tname,
            "surface": surf, "round": rnd, "score": score,
            "minutes": minutes, "best_of": best_of,
            "sets": sets_in(score),
            "winner_name": wname, "loser_name": lname,
            "champion_won": mine_won,
            # Whose aces are whose: the file stores them by result, not by name.
            "champion_aces": (w_ace if mine_won else l_ace),
            "opponent_aces": (l_ace if mine_won else w_ace),
        })
    wins = sum(1 for r in rows if r[7] == tml_id)
    return {"total": len(rows), "shown": len(out),
            "champion_wins": wins, "opponent_wins": len(rows) - wins,
            "matches": out}


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
    rows = conn.execute(f"""
        SELECT w_ace, minutes, score
        FROM tml_matches
        WHERE tour = ? AND surface = ? AND best_of = ? AND tourney_level IN {levels}
          AND tourney_date >= ? AND tourney_date <= ?
          AND score NOT LIKE '%W/O%'
          AND w_ace IS NOT NULL AND w_ace <= ?
          AND minutes IS NOT NULL AND minutes > 0 AND minutes <= ?""",
        (tour, surface, best_of, f"{year}-01-01", f"{year}-12-31", cap["aces"], cap["minutes"])).fetchall()
    if not rows:
        return None
    n = len(rows)
    sets_total = sum(sets_in(r[2]) for r in rows)
    return {"aces": int(round(sum(r[0] for r in rows) / n)),
            "minutes": int(round(sum(r[1] for r in rows) / n)),
            # THE THIRD DEFAULT (owner, 2026-09-19). Rounded, because the
            # answer is a whole number of sets: at 2.4 the average match is a
            # straight-sets win, which is what a bracket holding the default
            # should be taken to have said.
            "sets": int(round(sets_total / n)) if sets_total else None,
            "matches": n, "year": year}


# ── THE THREE TIEBREAK QUESTIONS' REFERENCE FIGURES (owner, 2026-09-19) ──────
#
# Every figure below is conditioned on the DRAW the questions belong to: its
# tour, its tier, its surface, and the two players that bracket has picked for
# the final. A WTA 250 on clay must never be answered with ATP hard numbers.
#
# THE TIER VOCABULARIES DO NOT MATCH, and folding them is the whole reason this
# table exists. Our draws carry "Grand Slam" / "ATP 1000" / "WTA 250" and
# Draw.scoring_tier reduces that to GS/1000/500/250. Sackmann's file spells the
# same thing per tour and per ERA: the ATP's old 250s are 'A', and the WTA ran
# Premier / Premier 5 / Premier Mandatory before the 2021 rename to 500/1000 —
# ten years of finals spans that change, so the legacy names have to come with
# their modern equivalent or a 1000's sample loses half its history.
TIER_LEVELS = {
    "atp": {"GS": ("G",), "1000": ("M",), "500": ("500",), "250": ("250", "A")},
    "wta": {"GS": ("G",), "1000": ("1000", "PM", "P5"), "500": ("500", "P"),
            "250": ("250", "I")},
}
# How far back each figure looks. The owner's own numbers: ten years for how
# many SETS a final goes, five for the per-set rates. Sets is one number per
# match and a decade of one tier's finals is still only a few dozen of them;
# aces and minutes get a reading per set, so five years is already thousands.
SETS_YEARS = 10
RATE_YEARS = 5
# What a changeover between sets costs: 225 seconds each, taken (sets - 1)
# times (owner, 2026-09-19).
#
# IT COMES OUT BEFORE ANY AVERAGING AND GOES BACK ON AFTERWARDS. The record
# stores whole-match `minutes`, breaks included, so total/sets is a per-set
# figure with the breaks of THAT match's set count amortised into it. Scaling
# such a figure to a different set count carries the wrong number of breaks,
# and adding 225s on top of it counts them twice.
#
# So every per-set duration here is PLAYING time: strip (sets - 1) breaks from
# each match before dividing, average that, and let estimate_minutes put the
# breaks back for the set count the reader actually predicted. A three-set
# prediction then carries two breaks whatever the history went.
BETWEEN_SETS_SECONDS = 225
BREAK_MINUTES = BETWEEN_SETS_SECONDS / 60


def _play_minutes(total: Optional[int], sets: int) -> Optional[float]:
    """One match's PLAYING minutes: the clock less its changeovers.

    Clamped at zero. A mis-recorded 40-minute three-setter would otherwise
    contribute negative playing time and drag an average below the floor.
    """
    if total is None or not sets:
        return None
    return max(0.0, total - BREAK_MINUTES * (sets - 1))


def set_lengths(best_of: int) -> tuple:
    """The set counts a final of this format can go.

    A best-of-three final is two or three sets and a best-of-five is three,
    four or five — never four for the former. One definition, imported by the
    cache and the endpoint alike, because two copies drift.
    """
    return (3, 4, 5) if best_of == 5 else (2, 3)


def _levels_for(tour: str, tier: str) -> tuple:
    return TIER_LEVELS.get(tour, {}).get(tier, ())


def _years_ago(years: int, today: Optional[date] = None) -> str:
    d = today or date.today()
    try:
        return d.replace(year=d.year - years).isoformat()
    except ValueError:                      # 29 February
        return d.replace(year=d.year - years, day=28).isoformat()


def _in(values) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


def tier_finals(conn, tour: str, tier: str, surface: str, years: int,
                today: Optional[date] = None, best_of: Optional[int] = None) -> Optional[dict]:
    """What a final at THIS tour and tier, on THIS surface, has looked like.

    Finals only — the question is about a final, and a final is not an average
    match: it is two players who have each won five matches that fortnight.

    FORMAT MATTERS MORE THAN SURFACE, so it is the condition given up last. A
    best-of-five final simply has more sets in it, and one tier does mix the
    two: the ATP's legacy 'A' code is its old 250 level and six of those finals
    inside a ten-year window were best-of-five, which nudged the 250's sets
    average up (found auditing this, 2026-09-19). Passing the draw's own format
    removes them.

    Conditions are given up in order, and the caller is told what it got:
    surface first (there has never been a WTA 1000 on grass), then format.
    Claiming a figure for a surface or a format that never hosted the event is
    the failure this avoids.
    """
    levels = _levels_for(tour, tier)
    if not levels:
        return None
    since = _years_ago(years, today)
    base = f"""
        SELECT w_ace, l_ace, minutes, score FROM tml_matches
        WHERE tour = ? AND round = 'F' AND tourney_level IN {_in(levels)}
          AND tourney_date >= ? AND score NOT LIKE '%W/O%'"""

    def attempt(surf: bool, fmt: bool):
        sql, params = base, [tour, since]
        if surf:
            sql += " AND surface = ?"
            params.append(surface)
        if fmt and best_of:
            sql += " AND best_of = ?"
            params.append(best_of)
        return conn.execute(sql, tuple(params)).fetchall()

    # (surface, format) — both, then without the surface, then neither.
    for surf, fmt in ((True, True), (False, True), (True, False), (False, False)):
        rows = attempt(surf, fmt)
        if rows:
            out = _both_sides(rows)
            if out:
                out["surface_scoped"] = surf
                out["format_scoped"] = bool(fmt and best_of)
                out["years"] = years
            return out
    return None


def _both_sides(rows) -> Optional[dict]:
    """Per-set rates counting BOTH players' aces, plus sets per match.

    A tour baseline is about the match rather than about one player in it, so
    an ace is an ace whoever served it — the same reading tour_reference uses.
    """
    aces = sets_a = play = sets_m = sets_total = n = 0
    for wa, la, m, score in rows:
        s = sets_in(score)
        if not s:
            continue
        n += 1
        sets_total += s
        if wa is not None and la is not None:
            aces += wa + la
            sets_a += 2 * s
        if m is not None and m > 0:
            play += _play_minutes(m, s)
            sets_m += s
    if not n:
        return None
    return {"matches": n,
            "sets_per_match": round(sets_total / n, 2),
            "aces_per_set": round(aces / sets_a, 2) if sets_a else None,
            # PLAYING minutes per set — breaks stripped. estimate_minutes puts
            # them back for the predicted set count.
            "play_minutes_per_set": round(play / sets_m, 1) if sets_m else None}


def player_rates(conn, tour: str, tml_id: str, surface: Optional[str], years: int,
                 opponent_tml_id: Optional[str] = None,
                 today: Optional[date] = None) -> Optional[dict]:
    """One player's own rates — their aces per set, their minutes per set, and
    how many sets their matches go.

    Every round, not finals only: a player's serve does not change because it
    is a final, and restricting it would leave most of the field with nothing.
    `surface` None means every surface; `opponent_tml_id` narrows it to the
    matches between these two, which is the head-to-head the drawer shows.

    THE ACES ARE THIS PLAYER'S, not the winner's. The file stores them by
    result, so reading w_ace without checking who won attributes every defeat's
    aces to the wrong person.
    """
    if not tml_id:
        return None
    sql = """
        SELECT CASE WHEN winner_id = :p THEN w_ace ELSE l_ace END, minutes, score
        FROM tml_matches
        WHERE tour = :tour AND score NOT LIKE '%W/O%' AND tourney_date >= :since"""
    params = {"p": tml_id, "tour": tour, "since": _years_ago(years, today)}
    if opponent_tml_id:
        sql += " AND ((winner_id = :p AND loser_id = :o) OR (winner_id = :o AND loser_id = :p))"
        params["o"] = opponent_tml_id
    else:
        sql += " AND (winner_id = :p OR loser_id = :p)"
    if surface:
        sql += " AND surface = :surface"
        params["surface"] = surface
    rows = conn.execute(sql, params).fetchall()
    got = _rate(rows)
    if not got:
        return None
    sets_total = play = sets_m = 0
    for _a, m, score in rows:
        st = sets_in(score)
        if not st:
            continue
        sets_total += st
        if m is not None and m > 0:
            play += _play_minutes(m, st)
            sets_m += st
    got["sets_per_match"] = round(sets_total / got["matches"], 2) if got["matches"] else None
    # Breaks stripped, like every per-set duration here. `minutes_per_set` from
    # _rate still carries them, so it is dropped rather than left to be read by
    # mistake — the two are different quantities.
    got.pop("minutes_per_set", None)
    got["play_minutes_per_set"] = round(play / sets_m, 1) if sets_m else None
    got["years"] = years
    return got


def h2h_sets(conn, tour: str, tml_id: str, opponent_tml_id: str, surface: str) -> dict:
    """How many sets these two have gone, on this surface and overall.

    ALL TIME, unlike the rates: a head-to-head is a short list and its oldest
    entry still answers "how do these two usually play". Two figures, and the
    second only earns its place when it says something the first does not —
    `off_surface` counts the meetings that were somewhere else, so the caller
    can drop an "all surfaces" row that would just repeat the surface one.
    """
    if not tml_id or not opponent_tml_id:
        return {"on_surface": None, "overall": None, "off_surface": 0}
    rows = conn.execute("""
        SELECT surface, score FROM tml_matches
        WHERE tour = ?
          AND ((winner_id = ? AND loser_id = ?) OR (winner_id = ? AND loser_id = ?))
          AND score NOT LIKE '%W/O%'""",
        (tour, tml_id, opponent_tml_id, opponent_tml_id, tml_id)).fetchall()
    played = [(surf, sets_in(sc)) for surf, sc in rows if sets_in(sc)]
    if not played:
        return {"on_surface": None, "overall": None, "off_surface": 0}
    here = [s for surf, s in played if surf == surface]
    return {
        "on_surface": ({"matches": len(here), "sets_per_match": round(sum(here) / len(here), 2)}
                       if here else None),
        "overall": {"matches": len(played),
                    "sets_per_match": round(sum(s for _, s in played) / len(played), 2)},
        "off_surface": len(played) - len(here),
    }


def h2h_set_minutes(conn, tour: str, tml_id: str, opponent_tml_id: str,
                    surface: str) -> Optional[dict]:
    """The average SET between these two on this surface, in minutes.

    The owner's arithmetic for the duration estimate: this figure times the
    number of sets the reader chose, plus 225 seconds for each changeover
    between them (estimate_minutes below). All time, like h2h_sets, and this
    surface only — the owner asked for the row to appear only when they have
    met on it.
    """
    if not tml_id or not opponent_tml_id:
        return None
    rows = conn.execute("""
        SELECT minutes, score FROM tml_matches
        WHERE tour = ? AND surface = ?
          AND ((winner_id = ? AND loser_id = ?) OR (winner_id = ? AND loser_id = ?))
          AND score NOT LIKE '%W/O%' AND minutes IS NOT NULL AND minutes > 0""",
        (tour, surface, tml_id, opponent_tml_id, opponent_tml_id, tml_id)).fetchall()
    play = sets = 0
    n = 0
    for m, score in rows:
        s = sets_in(score)
        if not s:
            continue
        n += 1
        play += _play_minutes(m, s)
        sets += s
    if not sets:
        return None
    return {"matches": n, "play_minutes_per_set": round(play / sets, 1)}


def estimate_minutes(play_minutes_per_set: Optional[float], sets: int) -> Optional[int]:
    """A duration for a final of `sets` sets: playing time times the sets, plus
    a changeover between each pair of them.

    TAKES PLAYING TIME, NOT A RAW PER-SET AVERAGE. Its input must already have
    had the breaks stripped (see BREAK_MINUTES) — that is what lets the number
    of breaks follow the reader's PREDICTION rather than whatever the history
    happened to go. Handing it a total/sets figure counts every break twice.
    """
    if play_minutes_per_set is None or not sets:
        return None
    return int(round(play_minutes_per_set * sets + BREAK_MINUTES * (sets - 1)))
