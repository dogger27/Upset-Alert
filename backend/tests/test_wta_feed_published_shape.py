"""The WTA feed's PUBLISHED shape: a match on a sheet that has not been played.

Singapore's qualifying day (2026-09-19), as the WTA's JSON stated it the
evening before: no CourtID and no DateSeq, the court in `CourtName`, the
sheet's wording in `NotBefore`, and every "Followed By" match stamped 23:59
and `Unscheduled` — in no court order. Read as the played shape, all eight
went on one blank court, chained to 11:36 PM, where the sheet printed two
courts of four (feed document 306; Korea's 307 the same).
"""
import json
from datetime import date
from types import SimpleNamespace

from app.services.oop_parser import Match
from app.services.schedule import _start_type_of
from app.services.schedule_feeds import declined, parse_day_document
from app.services.schedule_invariants import (court_opened_twice, court_unnamed,
                                              feed_order_unstated)
from app.services.wta_feed import matches_for_day, unordered_courts

DAY = date(2026, 9, 19)
TZ = "Asia/Singapore"


def _pub(mid, court, ts, wording, a, b):
    row = {"MatchID": mid, "CourtName": court, "DrawLevelType": "Q", "DrawMatchType": "S",
           "RoundID": 11, "MatchState": "U", "MatchTimeStamp": ts, "NotBefore": wording,
           "NotBeforeText": "", "FreeText": "", "isEstimatedStartTime": None,
           "SeedA": "", "SeedB": "", "EntryTypeA": "", "EntryTypeB": "",
           "PlayerNameFirstA": a[0], "PlayerNameLastA": a[1], "PlayerCountryA": a[2],
           "PlayerNameFirstB": b[0], "PlayerNameLastB": b[1], "PlayerCountryB": b[2]}
    if wording == "Followed By":
        row["Unscheduled"] = True
    return row


# The feed's own array order, which is no court's order.
SINGAPORE = [
    _pub("RS015", "Center Court", "2026-09-19T11:00+08:00", "Starting at 11:00 AM",
         ("Jiaqi", "Wang", "CHN"), ("Anastasia", "Kulikova", "FIN")),
    _pub("RS014", "Court 1", "2026-09-19T11:00+08:00", "Starting at 11:00 AM",
         ("Anna-Lena", "Friedsam", "GER"), ("Desirae", "Krawczyk", "USA")),
    _pub("RS009", "Court 1", "2026-09-19T23:59+08:00", "Followed By",
         ("Nika", "Radisic", "SLO"), ("Viktoria", "Morvayova", "SVK")),
    _pub("RS011", "Court 1", "2026-09-19T23:59+08:00", "Followed By",
         ("Aoi", "Ito", "JPN"), ("Sofya", "Lansere", "")),
    _pub("RS010", "Center Court", "2026-09-19T23:59+08:00", "Followed By",
         ("Nao", "Hibino", "JPN"), ("Kai Ning Chanya", "Ng", "SGP")),
    _pub("RS013", "Center Court", "2026-09-19T23:59+08:00", "Followed By",
         ("Eva Marie", "Desvignes", "SGP"), ("Kyoka", "Okamura", "JPN")),
    _pub("RS012", "Court 1", "2026-09-19T23:59+08:00", "Followed By",
         ("Mei", "Yamaguchi", "JPN"), ("Ulrikke", "Eikeri", "NOR")),
    _pub("RS008", "Center Court", "2026-09-19T23:59+08:00", "Followed By",
         ("Joanna", "Garland", "TPE"), ("Ellen", "Perez", "AUS")),
]


def test_a_published_match_is_on_the_court_the_feed_names():
    ms = matches_for_day(SINGAPORE, DAY, venue_tz=TZ)
    assert {m.court for m in ms} == {"Center Court", "Court 1"}
    assert sum(m.court == "Center Court" for m in ms) == 4
    # Through the learned mapping when there is one.
    ms = matches_for_day(SINGAPORE, DAY, court_names={"Center Court": "CENTER COURT"}, venue_tz=TZ)
    assert sum(m.court == "CENTER COURT" for m in ms) == 4


def test_a_published_match_keeps_the_sheets_wording():
    ms = matches_for_day(SINGAPORE, DAY, venue_tz=TZ)
    opener = next(m for m in ms if "WANG" in m.side_a[0])
    assert (opener.time, opener.start_raw, _start_type_of(opener)) == (
        "11:00", "Starting at 11:00 AM", "fixed")
    follower = next(m for m in ms if "GARLAND" in m.side_a[0])
    assert follower.time is None and _start_type_of(follower) == "followed_by"
    # Guadalajara's Bucsa v Jovic, 2026-09-18: a floor, not a fixed start.
    nb = _pub("LS003", "Estadio Skarch", "2026-09-19T17:00+08:00", "Not before 5:00 PM",
              ("Cristina", "Bucsa", "ESP"), ("Iva", "Jovic", "USA"))
    assert _start_type_of(matches_for_day([nb], DAY, venue_tz=TZ)[0]) == "not_before"


def test_the_feed_states_no_order_among_followed_by_matches():
    ms = matches_for_day(SINGAPORE, DAY, venue_tz=TZ)
    assert sorted(unordered_courts(ms)) == ["Center Court", "Court 1"]


def test_one_follower_after_an_opener_is_an_order():
    ms = matches_for_day(SINGAPORE[:1] + [SINGAPORE[4]], DAY, venue_tz=TZ)
    assert unordered_courts(ms) == []


def test_a_follower_beside_a_later_floor_is_no_order():
    # Guadalajara 2026-09-18: "Starting at 3:00 PM", "Not before 5:00 PM",
    # "Followed By" — the follower may come second as easily as third.
    rows = [_pub("LD003", "Estadio Skarch", "2026-09-19T15:00+08:00", "Starting at 3:00 PM",
                 ("Quinn", "Gleason", "USA"), ("Momoko", "Kobori", "JPN")),
            _pub("LS003", "Estadio Skarch", "2026-09-19T17:00+08:00", "Not before 5:00 PM",
                 ("Cristina", "Bucsa", "ESP"), ("Iva", "Jovic", "USA")),
            _pub("LS002", "Estadio Skarch", "2026-09-19T23:59+08:00", "Followed By",
                 ("Liudmila", "Samsonova", "RUS"), ("Peyton", "Stearns", "USA"))]
    assert unordered_courts(matches_for_day(rows, DAY, venue_tz=TZ)) == ["Estadio Skarch"]
    # Once the two ahead of it are PLAYED (CourtID, real starts) it can only be last.
    played = [dict(r, CourtID=1, DateSeq=6, NotBefore=None, CourtName=None,
                   MatchTimeStamp=ts) for r, ts in
              ((rows[0], "2026-09-19T07:02:11.5+00:00"), (rows[1], "2026-09-19T09:15:40+00:00"))]
    ms = matches_for_day(played + rows[2:], DAY, court_names={"CourtID 1": "Estadio Skarch"}, venue_tz=TZ)
    assert unordered_courts(ms) == []


def test_the_feeds_decline_a_day_they_cannot_state():
    doc = json.dumps({"day": "2026-09-19", "wta": json.dumps(SINGAPORE), "sofa": []}).encode()
    ms, meta = parse_day_document(doc, court_names={}, venue_tz=TZ)
    assert len(ms) == 8 and meta["unnamed"] == 0
    assert "no order on" in declined(meta)
    # A row with no court anywhere is declined too — the guard lost at 10:47 UTC.
    blank = [dict(SINGAPORE[0], CourtName=None)]
    doc = json.dumps({"day": "2026-09-19", "wta": json.dumps(blank), "sofa": []}).encode()
    _ms, meta = parse_day_document(doc, court_names={}, venue_tz=TZ)
    assert "no court" in declined(meta)
    # A day the feed CAN state is not declined.
    doc = json.dumps({"day": "2026-09-19", "wta": json.dumps(SINGAPORE[:2]), "sofa": []}).encode()
    _ms, meta = parse_day_document(doc, court_names={}, venue_tz=TZ)
    assert declined(meta) is None


def _row(i, court, order, start_type="followed_by", clock=None, doc=306):
    return SimpleNamespace(id=i, court=court, court_order=order, start_type=start_type,
                           start_time_local=clock, last_document_id=doc,
                           started_at=None, completed_at=None, winner_side=None)


def test_the_law_convicts_the_stored_incident():
    # As documents 306/307 stored it: one blank court, two 11:00 openers.
    rows = [_row(1, "", 1, "fixed", "11:00"), _row(2, "", 2, "fixed", "11:00")] + [
        _row(3 + i, "", 3 + i) for i in range(6)]
    assert len(court_unnamed(rows)) == 8
    assert [(a.id, b.id) for a, b in court_opened_twice(rows)] == [(2, 1)]
    assert [len(rs) for rs in feed_order_unstated(rows, {306})] == [6]
    # The same shape from a sheet is the page's own order, not a feed's guess.
    assert feed_order_unstated(rows, {999}) == []


def test_the_law_passes_the_day_as_the_sheet_prints_it():
    rows = []
    for c, court in enumerate(("CENTER COURT", "COURT 1")):
        rows.append(_row(10 * c + 1, court, 1, "fixed", "11:00 AM", doc=310))
        rows += [_row(10 * c + 2 + i, court, 2 + i, doc=310) for i in range(3)]
    assert court_unnamed(rows) == [] and court_opened_twice(rows) == []
    assert feed_order_unstated(rows, {306}) == []
    # A feed's single follower after an opener is an order.
    assert feed_order_unstated([_row(1, "A", 1, "fixed", "11:00"), _row(2, "A", 2)], {306}) == []


def test_match_published_defaults_false_for_every_other_source():
    assert Match().published is False
