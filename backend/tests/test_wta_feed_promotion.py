"""The WTA's own JSON is the schedule on a WTA-only day (owner, 2026-09-18):
the rule that picks it, the court name it renders with, and the vote floor
under a learned name.
"""
from datetime import date

from app.services.schedule_shadow import court_winners
from app.services.wta_feed import matches_for_day


def _row(court_id, seq, last_a, last_b, ts="2026-09-17T14:00:00Z"):
    return {"CourtID": court_id, "DateSeq": seq, "MatchTimeStamp": ts, "RoundID": "1",
            "DrawMatchType": "S", "PlayerNameFirstA": "A", "PlayerNameLastA": last_a,
            "PlayerNameFirstB": "B", "PlayerNameLastB": last_b,
            "PlayerCountryA": "BRA", "PlayerCountryB": "ARG"}


def test_the_learned_name_is_found_under_the_feed_court_string():
    rows = [_row(1, 1, "Dabrowski", "Pereira"), _row(3, 1, "Avanesyan", "Charaeva")]
    names = {"CourtID 1": "QUADRA CENTRAL MARIA ESTHER BUENO", "CourtID 3": "QUADRA 2"}
    got = {m.side_a[0]: m.court for m in matches_for_day(rows, date(2026, 9, 17), court_names=names)}
    assert got["A DABROWSKI BRA"] == "QUADRA CENTRAL MARIA ESTHER BUENO"
    assert got["A AVANESYAN BRA"] == "QUADRA 2"


def test_a_court_without_a_learned_name_has_none():
    # Not "Court 2" — a guess that is some real court's name (Singapore,
    # 2026-09-19; see test_wta_court_id_namespace).
    rows = [_row(2, 1, "Lamens", "Sierra")]
    ms = matches_for_day(rows, date(2026, 9, 17), court_names={"CourtID 1": "ESTADIO"})
    assert ms[0].court == "" and ms[0].court_key == "CourtID 2"


def test_court_winners_need_the_votes():
    tally = {"CourtID 1": {"ESTADIO": 70, "GRANDSTAND": 2}, "CourtID 4": {"A": 1, "B": 1},
             "CourtID 5": {}}
    assert court_winners(tally) == {"CourtID 1": "ESTADIO", "CourtID 4": "A"}
    assert court_winners(tally, min_votes=3) == {"CourtID 1": "ESTADIO"}


def test_a_feed_row_without_a_court_id_has_no_court_name():
    # The sheet keeps such a day (order_of_play._wta_feed_document): a blank
    # court on the page is worse than a parsed PDF.
    rows = [_row(None, 1, "Kostyuk", "Samsonova")]
    ms = matches_for_day(rows, date(2026, 9, 17), court_names={"Court 1": "ESTADIO SKARCH"})
    assert ms[0].court == ""


def test_the_wta_placeholder_time_is_no_time():
    rows = [dict(_row(None, None, "Samsonova", "Stearns", ts="2026-09-17T23:59:00Z"))]
    ms = matches_for_day(rows, date(2026, 9, 17), court_names={})
    assert ms[0].time is None and ms[0].start_raw is None
    placed = [dict(_row(1, 2, "Samsonova", "Stearns", ts="2026-09-17T23:59:00Z"))]
    assert matches_for_day(placed, date(2026, 9, 17), court_names={})[0].time == "23:59"
