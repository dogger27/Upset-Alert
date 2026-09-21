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
    ms, meta = parse_day_document(doc, court_names={"CourtID 1": "ESTADIO", "Grandstand": "GRANDSTAND"}, venue_tz="UTC")
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


def test_a_feed_estimate_is_not_a_printed_clock():
    """Sofascore staggers an estimate per court and the WTA flags its own;
    both spell it "Est. 14:00". Read as a printed clock it tripped
    printed_clock_runs_backwards on SP Open's Friday (2026-09-18)."""
    from datetime import date as _d
    from types import SimpleNamespace as NS
    from app.services.schedule import _start_type_of
    from app.services.schedule_invariants import _printed_instant

    assert _start_type_of(NS(start_raw="Est. 12:48", time="12:48")) == "estimated"
    assert _start_type_of(NS(start_raw="est 2:00 PM", time="2:00 PM")) == "estimated"
    assert _start_type_of(NS(start_raw="2:00 PM", time="2:00 PM")) == "fixed"
    assert _start_type_of(NS(start_raw="Not before 3:30 PM", time="3:30 PM")) == "not_before"
    assert _start_type_of(NS(start_raw="Followed by", time=None)) == "followed_by"

    estimated = NS(start_time_local="12:48", start_type="estimated", play_date=_d(2026, 9, 18))
    printed = NS(start_time_local="12:48", start_type="fixed", play_date=_d(2026, 9, 18))
    assert _printed_instant(estimated, "America/Sao_Paulo") is None
    assert _printed_instant(printed, "America/Sao_Paulo") is not None


def test_a_womans_day_is_topped_up_from_sofascore_when_the_wta_feed_is_thin():
    """SP Open's Friday: the WTA feed had 2 of 7 matches, Sofascore all 7.
    Offering both keeps the WTA row where it exists and fills the rest, so no
    other document is left owning part of the day (2026-09-18)."""
    # A doubles row as the WTA feed really sends one: all four players.
    wta = [{"MatchID": "dab-que", "CourtID": 1, "DateSeq": 2, "RoundID": "Q",
            "MatchTimeStamp": "2026-09-18T15:48:00Z", "DrawMatchType": "D",
            "PlayerNameFirstA": "Gabriela", "PlayerNameLastA": "Dabrowski", "PlayerCountryA": "CAN",
            "PlayerNameFirstA2": "Luisa", "PlayerNameLastA2": "Stefani", "PlayerCountryA2": "BRA",
            "PlayerNameFirstB": "Kaitlin", "PlayerNameLastB": "Quevedo", "PlayerCountryB": "ESP",
            "PlayerNameFirstB2": "Dominika", "PlayerNameLastB2": "Salkova", "PlayerCountryB2": "CZE"}]
    sofa = [_sofa("Dabrowski G / Stefani L", "Quevedo K / Salkova D", "Quadra 1", 15, 48),
            _sofa("Barros V L / Leme Da Silva N", "Strakhova V / Tikhonova A", "Quadra 1", 17, 0),
            _sofa("Stoiana M / Valdmannova V", "Dang Y / You X", "Quadra 1", 18, 40)]
    doc = _doc(wta, [("doubles", "WTA", sofa, False)])
    ms, meta = parse_day_document(doc, court_names={}, venue_tz="UTC")
    assert len(ms) == 3, [m.side_a for m in ms]          # the whole day, not two rows
    assert meta["wta"] == 1 and meta["sofa"] == 3
    # The match both sources hold appears once, in the WTA's own rendering.
    dab = [m for m in ms if any("abrowski" in n.lower() for n in m.side_a + m.side_b)]
    assert len(dab) == 1                                   # once, not twice
    assert "DABROWSKI CAN" in " ".join(dab[0].side_a)      # and in the WTA's own rendering


def test_a_sofascore_row_sharing_a_player_with_a_wta_row_is_that_match():
    """Korea's qualifying day (2026-09-19): the alternate Kuramochi replaced
    Zidanšek against Jeong. The WTA said so and Sofascore did not, the two
    sigs differed, and the day carried both — a phantom on GRANDSTAND."""
    wta = [_wta("Miho", "Kuramochi", "Boyoung", "Jeong", 1, 1, 5, 54)]
    sofa = [_sofa("Tamara Zidanšek", "Boyoung Jeong", "Grandstand", 4, 20),
            _sofa("Alevtina Ibragimova", "Rina Saigo", "Grandstand", 7, 0)]
    ms, _ = parse_day_document(_doc(wta, [("singles", "WTA", sofa, False)]),
                               court_names={"CourtID 1": "GRANDSTAND", "Grandstand": "GRANDSTAND"},
                               venue_tz="UTC")
    assert len(ms) == 2, [m.side_a + m.side_b for m in ms]   # the real match and the top-up
    assert not any("Zidan" in n for m in ms for n in m.side_a + m.side_b)


def test_a_day_with_every_stored_match_is_not_thin_whatever_the_count():
    """Guadalajara 2026-09-19: document 327 counted 3 for a 2-match day (a
    duplicate the ingest merged), and the guard refused the WTA's correct
    2-match day on every tick after. Fewer is thinner only when a stored match
    has no counterpart."""
    from app.services.schedule_feeds import accounts_for
    wta = [_wta("Peyton", "Stearns", "Iva", "Jovic", 1, 1, 23, 0)]
    ms, _ = parse_day_document(_doc(wta, []), court_names={"CourtID 1": "ESTADIO"}, venue_tz="UTC")
    stored = [("singles", {"stearns", "jovic"})]
    assert accounts_for(stored, ms)
    # A stored slot whose one player is still on the day (a replaced opponent).
    assert accounts_for([("singles", {"zidansek", "jovic"})], ms)
    # SP Open's Friday: stored matches the feed does not hold stay refused.
    assert not accounts_for(stored + [("singles", {"badosa", "podoroska"})], ms)
    # A different discipline is not a counterpart, and a nameless row is unproven.
    assert not accounts_for([("doubles", {"stearns", "jovic"})], ms)
    assert not accounts_for([("singles", set())], ms)
    assert not accounts_for([], ms)


def _feed_day(draws, monkeypatch, sofa_rows=()):
    """build_day_document for 2026-09-22 with no WTA event id and Sofascore
    answering `sofa_rows` for every draw that has an id."""
    import asyncio
    from app.services import schedule_feeds, schedule_shadow

    async def no_event_id(*_a, **_k):
        return None

    async def sofa_parts(*_a, **_k):
        return list(sofa_rows)

    monkeypatch.setattr(schedule_shadow, "wta_event_id", no_event_id)
    monkeypatch.setattr(schedule_feeds, "_sofa_parts", sofa_parts)
    t = SimpleNamespace(id=17, name="Chengdu Open")
    return asyncio.run(schedule_feeds.build_day_document(
        None, t, draws, date(2026, 9, 22), 2026, "Asia/Shanghai"))


def test_a_draw_with_no_feed_to_ask_is_unfed_not_a_feed_gap(monkeypatch):
    """Chengdu 2026-09-22: the qualifying sheet published hours before the
    resolver stamped the draw's Sofascore id, so no feed was ever asked — and
    the PDF fallback warned that "no feed had a schedule" (system_logs 4118).
    The day is handed to the PDF all the same, with the reason."""
    got = _feed_day([_draw("M", sofa=False)], monkeypatch)
    assert got == {"unfed": "the men's draw has no Sofascore id yet", "sources": []}
    women = _feed_day([_draw("F", sofa=False)], monkeypatch)
    assert women["unfed"] == "the women's draw has no WTA event id or Sofascore id yet"
    # A combined event whose fed half has nothing for the day: the unfed half
    # is the explanation, and it has its own alarm in sofa_resolver.
    both = _feed_day([_draw("M", sofa=False), _draw("F")], monkeypatch)
    assert both["unfed"] == "the men's draw has no Sofascore id yet"


def test_every_draw_fed_and_none_with_the_day_is_still_a_gap(monkeypatch):
    assert _feed_day([_draw("M")], monkeypatch) is None


def test_only_a_day_every_feed_could_have_supplied_warns():
    from app.services.order_of_play import _pdf_fallback_note
    t = SimpleNamespace(id=17, name="Chengdu Open")
    day = date(2026, 9, 22)
    level, msg, key = _pdf_fallback_note(
        t, day, {}, {day: "the men's draw has no Sofascore id yet"})
    assert (level, key) == ("info", "pdf_unfed_17")
    assert "no feed had a schedule" not in msg and "no Sofascore id" in msg
    assert _pdf_fallback_note(t, day, {day: "3 row(s) with no court"}, {})[0] == "info"
    # Another day unfed says nothing about this one.
    assert _pdf_fallback_note(t, day, {}, {date(2026, 9, 23): "x"}) == (
        "warning", "Chengdu Open 2026-09-22: no feed had a schedule; the PDF filled in",
        "pdf_fallback_17")
