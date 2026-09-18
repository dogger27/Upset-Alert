"""An unplaced match in the WTA feed carries placeholders, not a schedule.

Guadalajara's semi-final day (2026-09-18), as the WTA's JSON stated it that
morning: no CourtID and no DateSeq on any match, RoundID the INTEGER 2 on all
three where every placed match states a string ("1", "2", "Q", "S", "F"), and
Samsonova v Stearns stamped 23:59. Read as given, every semi-final was an
"R2" and the untimed match opened the court ahead of the 3:00 PM doubles; the
sheet prints it third, "Followed by".
"""
from datetime import date

from app.services.oop_parser import Match, feed_order
from app.services.schedule_invariants import _law_round_number
from app.services.wta_feed import matches_for_day

DAY = date(2026, 9, 18)
TZ = "America/Mexico_City"


def _unplaced(mid, kind, ts, a, b):
    return {"MatchID": mid, "DrawMatchType": kind, "RoundID": 2, "MatchState": "U",
            "MatchTimeStamp": ts, "SeedA": "", "SeedB": "", "EntryTypeA": "",
            "EntryTypeB": "", "PlayerNameFirstA": a[0], "PlayerNameLastA": a[1],
            "PlayerCountryA": a[2], "PlayerNameFirstB": b[0],
            "PlayerNameLastB": b[1], "PlayerCountryB": b[2]}


ROWS = [
    _unplaced("LS002", "S", "2026-09-18T23:59-06:00",
              ("Liudmila", "Samsonova", "RUS"), ("Peyton", "Stearns", "USA")),
    _unplaced("LS003", "S", "2026-09-18T17:00-06:00",
              ("Cristina", "Bucsa", "ESP"), ("Iva", "Jovic", "USA")),
    _unplaced("LD003", "D", "2026-09-18T15:00-06:00",
              ("Quinn", "Gleason", "USA"), ("Momoko", "Kobori", "JPN")),
]


def test_an_integer_round_is_a_placeholder_not_a_round():
    ms = matches_for_day(ROWS, DAY, venue_tz=TZ)
    assert [m.round for m in ms] == [None, None, None]
    # A placed match's string round still reads as before.
    placed = dict(ROWS[1], RoundID="S", CourtID=1, DateSeq=2)
    assert matches_for_day([placed], DAY, venue_tz=TZ)[0].round == "SF"


def test_an_unplaced_match_is_last_on_its_court_not_first():
    ms = matches_for_day(ROWS, DAY, venue_tz=TZ)
    assert [(m.time, m.side_b[0].split()[1]) for m in ms] == [
        ("15:00", "KOBORI"), ("17:00", "JOVIC"), (None, "STEARNS")]


def test_the_shared_order_puts_untimed_last_within_each_court():
    rows = [Match(court="B", time=None), Match(court="A", time="18:00"),
            Match(court="A", time=None), Match(court="A", time="11:00")]
    assert [(m.court, m.time) for m in sorted(rows, key=feed_order)] == [
        ("A", "11:00"), ("A", "18:00"), ("A", None), ("B", None)]


def test_the_law_reads_a_round_label_the_way_every_source_writes_one():
    # A 32-draw has five rounds.
    for label, want in (("F", 5), ("SF", 4), ("QF", 3), ("R16", 2), ("R32", 1),
                        ("R1", 1), ("R2", 2), ("2R", 2), ("r2", 2)):
        assert _law_round_number(label, 5) == want, label
    for label in ("Q1", "Q", "FQ", "", None, "R12"):
        assert _law_round_number(label, 5) is None, label
    # The incident: "R2" on a semi-final contradicts its bracket match.
    assert _law_round_number("R2", 5) != 4
