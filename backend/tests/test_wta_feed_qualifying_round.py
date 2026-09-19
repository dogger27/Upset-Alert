"""A qualifying round in the WTA feed is a qualifying round.

Singapore's qualifying day (2026-09-19, main draw from 09-21), as the feed
states a played match: DrawLevelType "Q", RoundID "1". The level was never
read, so every played match that day was filed as main-draw R1.
"""
from datetime import date

from app.services.schedule import _classify
from app.services.wta_feed import matches_for_day

DAY = date(2026, 9, 19)
TZ = "Asia/Singapore"


def _row(mid, level, rid, cid=2, ts="2026-09-19T02:47:24.373+00:00"):
    return {"MatchID": mid, "DrawLevelType": level, "DrawMatchType": "S", "RoundID": rid,
            "CourtID": cid, "DateSeq": 1 if cid else None, "MatchTimeStamp": ts,
            "PlayerNameFirstA": "Anna-Lena", "PlayerNameLastA": f"Friedsam{mid}",
            "PlayerCountryA": "GER", "PlayerNameFirstB": "Desirae",
            "PlayerNameLastB": f"Krawczyk{mid}", "PlayerCountryB": "USA"}


def test_a_qualifying_round_is_q_and_its_number():
    ms = matches_for_day([_row("RS014", "Q", "1"), _row("RS020", "Q", "2")], DAY, venue_tz=TZ)
    assert sorted(m.round for m in ms) == ["Q1", "Q2"]
    assert all(_classify(m)[0] == "qualifying" for m in ms)


def test_a_main_draw_round_is_unchanged():
    ms = matches_for_day([_row("LS001", "M", "1"), _row("LS002", "M", "S")], DAY, venue_tz=TZ)
    assert sorted(m.round for m in ms) == ["R1", "SF"]
    assert all(_classify(m)[0] == "main" for m in ms)


def test_an_unplaced_qualifying_round_is_still_a_placeholder():
    # The INTEGER 11 the feed puts on a published qualifying row is no round
    # (test_wta_feed_unplaced_match); the day and the players settle its stage.
    row = _row("RS012", "Q", 11, cid=None, ts="2026-09-19T23:59+08:00")
    row["CourtName"] = "Court 1"
    [m] = matches_for_day([row], DAY, venue_tz=TZ)
    assert m.round is None
