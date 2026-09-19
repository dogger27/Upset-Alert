"""A numbered WTA court is not a court CALLED by that number.

Singapore 2026-09-19, feed document 328 (14:41 local): the three matches
played on CENTER COURT came back in the feed's played shape as CourtID 1, and
were filed on COURT 1. The learned mapping keyed CourtID 1 as "Court 1" — the
name Sofascore and the WTA's own published rows give the real COURT 1 — so the
key held COURT 1 106, CENTER COURT 14, and the majority won. Center Court was
left with its one unplayed "Followed By" match as its opener
(`court_opener_untimed`), and COURT 1 had two matches starting 17 minutes apart.
"""
import json
from datetime import date

from app.services.schedule_feeds import declined, parse_day_document
from app.services.schedule_shadow import court_votes, court_winners
from app.services.wta_feed import court_id_key, matches_for_day

DAY = date(2026, 9, 19)
TZ = "Asia/Singapore"

# app_settings sofa_courts:82 as it stood when document 328 was written.
SINGAPORE_TALLY = {"Center Court": {"CENTER COURT": 106},
                   "Court 1": {"CENTER COURT": 14, "COURT 1": 106},
                   "Court 2": {"COURT 1": 13}}


def _played(mid, cid, ts, a, b):
    return {"MatchID": mid, "CourtID": cid, "DateSeq": 1, "MatchTimeStamp": ts,
            "RoundID": "1", "DrawMatchType": "S", "DrawLevelType": "Q",
            "PlayerNameFirstA": a[0], "PlayerNameLastA": a[1], "PlayerCountryA": a[2],
            "PlayerNameFirstB": b[0], "PlayerNameLastB": b[1], "PlayerCountryB": b[2]}


def _published(mid, court, a, b):
    return {"MatchID": mid, "CourtName": court, "NotBefore": "Followed By",
            "Unscheduled": True, "MatchTimeStamp": "2026-09-19T23:59+08:00",
            "RoundID": 11, "DrawMatchType": "S", "DrawLevelType": "Q",
            "PlayerNameFirstA": a[0], "PlayerNameLastA": a[1], "PlayerCountryA": a[2],
            "PlayerNameFirstB": b[0], "PlayerNameLastB": b[1], "PlayerCountryB": b[2]}


# The feed at 06:48 UTC: CourtID 1 is Center Court, CourtID 2 is Court 1.
FEED = [
    _played("RS014", 2, "2026-09-19T02:47:24.373+00:00", ("Anna-Lena", "Friedsam", "GER"), ("Desirae", "Krawczyk", "USA")),
    _played("RS015", 1, "2026-09-19T03:04:16.44+00:00", ("Jiaqi", "Wang", "CHN"), ("Anastasia", "Kulikova", "FIN")),
    _played("RS011", 2, "2026-09-19T04:30:49.347+00:00", ("Aoi", "Ito", "JPN"), ("Sofya", "Lansere", "")),
    _played("RS010", 1, "2026-09-19T04:48:24.317+00:00", ("Nao", "Hibino", "JPN"), ("Kai Ning Chanya", "Ng", "SGP")),
    _played("RS008", 1, "2026-09-19T05:56:24.62+00:00", ("Joanna", "Garland", "TPE"), ("Ellen", "Perez", "AUS")),
    _played("RS009", 2, "2026-09-19T06:36:10.627+00:00", ("Nika", "Radisic", "SLO"), ("Viktoria", "Morvayova", "SVK")),
    _published("RS013", "Center Court", ("Eva Marie", "Desvignes", "SGP"), ("Kyoka", "Okamura", "JPN")),
    _published("RS012", "Court 1", ("Mei", "Yamaguchi", "JPN"), ("Ulrikke", "Eikeri", "NOR")),
]

CENTER = {"WANG", "HIBINO", "GARLAND", "DESVIGNES"}


def _surname(m):
    return next(t for t in m.side_a[0].split() if t.isalpha() and t.isupper() and len(t) >= 3)


def test_a_court_called_court_n_does_not_lend_its_votes_to_courtid_n():
    names = court_winners(SINGAPORE_TALLY, min_votes=3)
    assert names["Court 1"] == "COURT 1"            # the named court, as it is
    assert court_id_key(1) not in names             # inseparable from it: not trusted
    assert names[court_id_key(2)] == "COURT 1"      # a number no court is called: kept


def test_old_numbered_votes_still_count_where_no_court_has_the_name():
    # SP Open, where no court is called "Court 3".
    tally = {"Court 3": {"QUADRA 2": 545, "QUADRA 1": 41}, "CourtID 3": {"QUADRA 2": 2}}
    assert court_winners(tally, min_votes=3)[court_id_key(3)] == "QUADRA 2"


def test_center_courts_played_matches_are_never_filed_on_court_1():
    names = court_winners(SINGAPORE_TALLY, min_votes=3)
    ms = matches_for_day(FEED, DAY, court_names=names, venue_tz=TZ)
    got = {_surname(m): m.court for m in ms}
    assert all(got[s] != "COURT 1" for s in CENTER)
    assert {got[s] for s in ("FRIEDSAM", "ITO", "RADISIC", "YAMAGUCHI")} == {"COURT 1"}
    # Unmapped, a numbered court is left unnamed rather than guessed.
    assert {got[s] for s in ("WANG", "HIBINO", "GARLAND")} == {""}


def _doc(sofa_events):
    return json.dumps({"day": DAY.isoformat(), "wta": json.dumps(FEED),
                       "sofa": ([{"disc": "singles", "tour": "WTA", "doc": json.dumps(sofa_events)}]
                                if sofa_events else [])}).encode()


def test_without_another_name_for_the_court_the_day_goes_to_the_sheet():
    names = court_winners(SINGAPORE_TALLY, min_votes=3)
    _ms, meta = parse_day_document(_doc(None), court_names=names, venue_tz=TZ)
    assert "no court" in (declined(meta) or "")


def test_sofascores_court_for_the_same_match_names_it():
    def ev(a, b, ts):
        return {"id": hash((a, b)) % 10**6, "startTimestamp": ts, "roundInfo": {"name": "Qualification"},
                "venue": {"name": "Center Court"},
                "homeTeam": {"name": a, "country": {"alpha3": "CHN"}},
                "awayTeam": {"name": b, "country": {"alpha3": "FIN"}}}
    sofa = [ev("Jiaqi Wang", "Anastasia Kulikova", 1789787040),
            ev("Nao Hibino", "Kai Ning Chanya Ng", 1789793280),
            ev("Joanna Garland", "Ellen Perez", 1789797360)]
    names = court_winners(SINGAPORE_TALLY, min_votes=3)
    ms, meta = parse_day_document(_doc(sofa), court_names=names, venue_tz=TZ)
    assert declined(meta) is None
    center = sorted((m for m in ms if m.court == "CENTER COURT"),
                    key=lambda m: (m.time is None, m.time or ""))
    assert [_surname(m) for m in center] == ["WANG", "HIBINO", "GARLAND", "DESVIGNES"]
    assert center[0].time                           # the court opens on a clock


def test_the_shadow_votes_a_numbered_court_under_its_own_key():
    ms = matches_for_day(FEED, DAY, venue_tz=TZ)
    wang = next(m for m in ms if _surname(m) == "WANG")
    yamaguchi = next(m for m in ms if _surname(m) == "YAMAGUCHI")
    votes = court_votes([({"court": "CENTER COURT"}, wang), ({"court": "COURT 1"}, yamaguchi)])
    assert votes == {court_id_key(1): {"CENTER COURT": 1}, "Court 1": {"COURT 1": 1}}
