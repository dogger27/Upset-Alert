"""The schedule from the feeds (owner, 2026-09-18): which feed serves each
draw, one document per day holding the women from the WTA and the men from
Sofascore, courts made to agree across the two, and a WTA row the feed left
unnamed taking its court from the women's Sofascore row for the same match.
"""
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.services.schedule_feeds import parse_day_document, plan


def _draw(gender, sofa=True):
    return SimpleNamespace(gender=gender, sofa_tournament_id=100 if sofa else None,
                           sofa_season_id=200 if sofa else None,
                           sofa_doubles_tournament_id=None, sofa_doubles_season_id=None)


def test_plan_sends_women_to_the_wta_and_men_to_sofascore():
    m, f = _draw("M"), _draw("F")
    assert [src for _, src in plan([m, f], wta_event_id=1139)] == ["sofa", "wta"]
    assert [src for _, src in plan([f], wta_event_id=None)] == ["sofa"]       # no WTA id: Sofascore
    assert [src for _, src in plan([_draw("M", sofa=False)], wta_event_id=None)] == ["none"]


def _ts(hh, mm, day=date(2026, 9, 18)):
    return int(datetime(day.year, day.month, day.day, hh, mm, tzinfo=timezone.utc).timestamp())


def _sofa(name_a, name_b, court, hh, mm):
    return {"id": hash((name_a, name_b)) % 10**6, "startTimestamp": _ts(hh, mm),
            "roundInfo": {"name": "Quarterfinal"}, "venue": {"name": court},
            "homeTeam": {"name": name_a, "country": {"alpha3": "USA"}},
            "awayTeam": {"name": name_b, "country": {"alpha3": "ESP"}}}


def _wta(first_a, last_a, first_b, last_b, court_id, seq, hh, mm):
    return {"MatchID": f"{last_a}-{last_b}", "CourtID": court_id, "DateSeq": seq, "RoundID": "Q",
            "MatchTimeStamp": f"2026-09-18T{hh:02d}:{mm:02d}:00Z", "DrawMatchType": "S",
            "PlayerNameFirstA": first_a, "PlayerNameLastA": last_a, "PlayerCountryA": "USA",
            "PlayerNameFirstB": first_b, "PlayerNameLastB": last_b, "PlayerCountryB": "ESP"}


def _doc(wta_rows, sofa_parts):
    return json.dumps({"day": "2026-09-18",
                       "wta": json.dumps(wta_rows) if wta_rows is not None else None,
                       "sofa": [{"disc": d, "tour": t, "doc": json.dumps(evs), **({"courts_only": True} if co else {})}
                                for d, t, evs, co in sofa_parts]}).encode()


def test_one_document_holds_the_women_from_the_wta_and_the_men_from_sofascore():
    doc = _doc([_wta("Peyton", "Stearns", "Sloane", "Stephens", 1, 1, 15, 0)],
               [("singles", "ATP", [_sofa("Ben Shelton", "Carlos Alcaraz", "Grandstand", 16, 0)], False)])
    ms, meta = parse_day_document(doc, court_names={"Court 1": "ESTADIO", "Grandstand": "GRANDSTAND"}, venue_tz="UTC")
    # The WTA rows are rendered the way a sheet prints a name (surname in
    # caps, the IOC code last); Sofascore's stay as they came.
    got = {(m.tour, m.side_a[0].split()[1].upper(), m.court) for m in ms}
    assert got == {("WTA", "STEARNS", "ESTADIO"), ("ATP", "SHELTON", "GRANDSTAND")}
    assert meta["wta"] == 1 and meta["sofa"] == 1 and meta["count"] == 2


def test_a_wta_row_without_a_court_takes_it_from_the_womens_sofascore_row():
    doc = _doc([_wta("Cristina", "Bucsa", "Iva", "Jovic", None, None, 17, 0)],
               [("singles", "WTA", [_sofa("Cristina Bucsa", "Iva Jovic", "Center Court", 17, 0)], True)])
    ms, meta = parse_day_document(doc, court_names={"Center Court": "ESTADIO SKARCH"}, venue_tz="UTC")
    assert len(ms) == 1                       # the courts-only rows are never emitted
    assert ms[0].tour == "WTA" and ms[0].court == "ESTADIO SKARCH"
    assert meta["sofa"] == 0


def test_a_match_offered_twice_is_kept_once():
    doc = _doc([_wta("Peyton", "Stearns", "Sloane", "Stephens", 1, 1, 15, 0)],
               [("singles", "WTA", [_sofa("Peyton Stearns", "Sloane Stephens", "Court 1", 15, 0)], False)])
    ms, _ = parse_day_document(doc, court_names={}, venue_tz="UTC")
    assert len(ms) == 1 and ms[0].court == "Court 1"


def test_sofascore_courts_go_through_the_learned_names_and_stay_themselves_otherwise():
    doc = _doc(None, [("singles", "ATP", [_sofa("A One", "B Two", "Stadium", 11, 0),
                                          _sofa("C Three", "D Four", "Court 5", 11, 0)], False)])
    ms, _ = parse_day_document(doc, court_names={"Stadium": "STADIUM COURT"}, venue_tz="UTC")
    assert {m.court for m in ms} == {"STADIUM COURT", "Court 5"}


def test_the_court_fill_matches_on_surnames_across_the_two_spellings():
    doc = _doc([_wta("Quinn", "Gleason", "Momoko", "Kobori", None, None, 15, 0)],
               [("doubles", "WTA", [_sofa("Gleason Q. / Piter K.", "Kobori M. / Plipuech P.", "Estadio", 15, 0)], True)])
    ms, _ = parse_day_document(doc, court_names={}, venue_tz="UTC")
    # The WTA row names two of the four players; Sofascore names all four.
    # Surname sets differ, so this pair is NOT matched — and nothing invents a court.
    assert ms[0].court == ""
    doc = _doc([_wta("Cristina", "Bucsa", "Iva", "Jovic", None, None, 17, 0)],
               [("singles", "WTA", [_sofa("Bucsa C.", "Jovic I.", "Estadio", 17, 0)], True)])
    ms, _ = parse_day_document(doc, court_names={}, venue_tz="UTC")
    assert ms[0].court == "Estadio"


def test_a_doubles_player_with_two_initials_keeps_both_before_the_surname():
    from app.services.sofa_schedule import _surname_last
    assert _surname_last("Barros V L") == "V L Barros"
    assert _surname_last("Bhambri Y") == "Y Bhambri"
    assert _surname_last("Van de Zandschulp B") == "B Van de Zandschulp"
    assert _surname_last("Daniel Altmaier") == "Daniel Altmaier"
