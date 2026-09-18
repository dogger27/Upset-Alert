"""The WTA's own JSON is the schedule on a WTA-only day (owner, 2026-09-18):
the rule that picks it, the court name it renders with, and the vote floor
under a learned name.
"""
from datetime import date

from app.services.order_of_play import use_wta_feed
from app.services.schedule_shadow import court_winners
from app.services.wta_feed import matches_for_day


def test_the_feed_takes_a_wta_only_day_and_leaves_a_combined_sheet_alone():
    assert use_wta_feed("WTA", covers_atp=False) is True
    assert use_wta_feed("WTA", covers_atp=True) is False      # the men are only on the sheet
    assert use_wta_feed("ATP", covers_atp=False) is False     # the feed holds women only
    assert use_wta_feed(None, covers_atp=False) is False


def _row(court_id, seq, last_a, last_b, ts="2026-09-17T14:00:00Z"):
    return {"CourtID": court_id, "DateSeq": seq, "MatchTimeStamp": ts, "RoundID": "1",
            "DrawMatchType": "S", "PlayerNameFirstA": "A", "PlayerNameLastA": last_a,
            "PlayerNameFirstB": "B", "PlayerNameLastB": last_b,
            "PlayerCountryA": "BRA", "PlayerCountryB": "ARG"}


def test_the_learned_name_is_found_under_the_feed_court_string():
    rows = [_row(1, 1, "Dabrowski", "Pereira"), _row(3, 1, "Avanesyan", "Charaeva")]
    names = {"Court 1": "QUADRA CENTRAL MARIA ESTHER BUENO", "Court 3": "QUADRA 2"}
    got = {m.side_a[0]: m.court for m in matches_for_day(rows, date(2026, 9, 17), court_names=names)}
    assert got["A Dabrowski"] == "QUADRA CENTRAL MARIA ESTHER BUENO"
    assert got["A Avanesyan"] == "QUADRA 2"


def test_a_court_without_a_learned_name_says_court_n():
    rows = [_row(2, 1, "Lamens", "Sierra")]
    ms = matches_for_day(rows, date(2026, 9, 17), court_names={"Court 1": "ESTADIO"})
    assert ms[0].court == "Court 2"


def test_court_winners_need_the_votes():
    tally = {"Court 1": {"ESTADIO": 70, "GRANDSTAND": 2}, "Court 4": {"A": 1, "B": 1}, "Court 5": {}}
    assert court_winners(tally) == {"Court 1": "ESTADIO", "Court 4": "A"}
    assert court_winners(tally, min_votes=3) == {"Court 1": "ESTADIO"}
