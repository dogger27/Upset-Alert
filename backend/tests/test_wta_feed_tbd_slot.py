"""A slot the WTA feed reserves before it knows who plays in it.

Korea's Sunday (2026-09-20), as the feed stated it on Saturday evening: two Q2
matches named, and two more — RS004 on Grandstand, RS006 on Show Court 1 —
with `PlayerIDA`/`PlayerIDB` "TBD", no names at all, "Time TBC". The sheet
released at 5:45 PM prints those two as "M. Kuramochi OR B. Jeong vs X. Yao
OR P. Hon" and "A. Ibragimova OR R. Saigo vs E. Liang OR S. Saito".

Taken as the day, both nameless rows hashed to one pairing key (no names and
no ids leave nothing to hash but the day), collapsed onto one schedule entry
with nobody in it, and the law convicted it: `entry_empty` on entry 1319,
feed document 340.
"""
import json
from datetime import date

from app.services.schedule_feeds import declined, parse_day_document

DAY = date(2026, 9, 20)
TZ = "Asia/Seoul"


def _row(mid, court, ts, wording, a=None, b=None):
    row = {"MatchID": mid, "CourtName": court, "DrawLevelType": "Q", "DrawMatchType": "S",
           "EventID": "1024", "EventYear": 2026, "RoundID": 10, "MatchState": "U",
           "MatchTimeStamp": ts, "NotBefore": wording, "FreeText": "",
           "PlayerIDA": "TBD", "PlayerIDB": "TBD"}
    for side, p in (("A", a), ("B", b)):
        if p:
            row.update({f"PlayerID{side}": p[0], f"PlayerNameFirst{side}": p[1],
                        f"PlayerNameLast{side}": p[2], f"PlayerCountry{side}": p[3]})
    if not wording:
        row.update(Unscheduled=True, FreeText="Time TBC")
    return row


KOREA = [
    _row("RS005", "Show Court 1", "2026-09-20T11:00+09:00", "Starting at 11:00 AM",
         ("330001", "Alexandra", "Shubladze", ""), ("330002", "Darya", "Astakhova", "")),
    _row("RS007", "Grandstand", "2026-09-20T11:00+09:00", "Starting at 11:00 AM",
         ("330003", "Eunhye", "Lee", "KOR"), ("330004", "Ye-Xin", "Ma", "CHN")),
    _row("RS004", "Grandstand", "2026-09-20T23:59+09:00", None),
    _row("RS006", "Show Court 1", "2026-09-20T23:59+09:00", None),
]


def _parse(rows):
    doc = json.dumps({"day": DAY.isoformat(), "wta": json.dumps(rows), "sofa": []}).encode()
    return parse_day_document(doc, court_names={}, venue_tz=TZ)


def test_a_slot_the_feed_names_nobody_in_declines_the_day():
    ms, meta = _parse(KOREA)
    assert len(ms) == 4 and meta["unnamed"] == 0 and meta["unordered"] == []
    assert meta["nameless"] == 2
    assert "2 row(s) naming nobody on a side" in declined(meta)


def test_one_side_still_to_be_decided_declines_it_too():
    # Ibragimova won her Q1, Liang v Saito is still on court: the sheet prints
    # "IBRAGIMOVA vs E. Liang OR S. Saito", the feed an empty side.
    half = _row("RS006", "Show Court 1", "2026-09-20T23:59+09:00", None,
                a=("330005", "Anastasia", "Ibragimova", ""))
    _ms, meta = _parse(KOREA[:3] + [half])
    assert meta["nameless"] == 2
    assert declined(meta)


def test_the_day_is_the_feeds_once_every_slot_names_its_players():
    filled = [
        KOREA[0], KOREA[1],
        _row("RS004", "Grandstand", "2026-09-20T23:59+09:00", None,
             ("330006", "Mayuka", "Kuramochi", "JPN"), ("330007", "Xinyu", "Yao", "CHN")),
    ]
    _ms, meta = _parse(filled)
    assert meta["nameless"] == 0
    assert declined(meta) is None


# THE SHEET THE DAY IS DECLINED TO has to parse, or declining trades an empty
# row for a mangled one: Korea's sheet heads each court's second box "Time
# TBC", which opened nothing, so the Q2 below it was read as more of Lee v Ma.
GRANDSTAND = ["GRANDSTAND", "Starting at 11:00 AM", "Q2", "[WC] Eunhye LEE KOR", "vs",
              "[5] Ye-Xin MA CHN", "Time TBC", "Q2", "M. Kuramochi OR", "B. Jeong", "vs",
              "X. Yao OR", "P. Hon"]


def test_time_tbc_opens_the_next_box_on_the_sheet():
    from app.services.oop_parser import _parse_column
    ms = _parse_column(list(enumerate(GRANDSTAND)), 1)
    assert [(m.side_a, m.side_b) for m in ms] == [
        (["[WC] Eunhye LEE KOR"], ["[5] Ye-Xin MA CHN"]),
        (["M. Kuramochi", "B. Jeong"], ["X. Yao", "P. Hon"])]
    assert ms[1].start_raw == "Time TBC" and ms[1].time is None
    assert ms[1].tbd and ms[1].tbd_side == "ab"


def test_time_tbc_is_a_marker_only_as_a_whole_line():
    from app.services.oop_parser import TBX_RE
    assert TBX_RE.match("Time TBC") and TBX_RE.match("TIME TBA") and TBX_RE.match("TBC")
    assert not TBX_RE.match("COURT TBA")                 # a court's name
    assert not TBX_RE.match("AFTER REST, TIME TBA")      # a slot by its own first words
