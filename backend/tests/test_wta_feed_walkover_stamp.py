"""A walkover's MatchTimeStamp is when the result was ENTERED, not a start.

SP Open 2026-09-18: Dabrowski/Stefani's doubles QF, printed "After suitable
rest - NB 4pm" second on QUADRA 1, went w/o when Quevedo walked on for her
singles. The WTA feed stamped it 15:48:22 UTC — 12:48 PM local — and the
feed reader wrote that over the sheet's wording as a FIXED "12:48" under the
court's 2:00 PM opener (printed_clock_runs_backwards), sorted first on its
court. The fields that say "walkover" are volatile and stripped from the
stored bytes, so the fact has to survive normalize_day on its own key.
"""
import json
from datetime import date

from app.services.wta_feed import matches_for_day, normalize_day, parse_wta_day

DAY = date(2026, 9, 18)
TZ = "America/Sao_Paulo"


def _played(mid, court, ts, a, b, score, result, total):
    return {"MatchID": mid, "DrawMatchType": "D", "RoundID": "Q", "MatchState": "F",
            "CourtID": court, "DateSeq": 7, "MatchTimeStamp": ts,
            "MatchTimeTotal": total, "ScoreString": score, "ResultString": result,
            "SeedA": "", "SeedB": "", "EntryTypeA": "", "EntryTypeB": "",
            "PlayerNameFirstA": a[0], "PlayerNameLastA": a[1], "PlayerCountryA": a[2],
            "PlayerNameFirstB": b[0], "PlayerNameLastB": b[1], "PlayerCountryB": b[2]}


WALKOVER = _played("LD004", 2, "2026-09-18T15:48:22.933+00:00",
                   ("Gabriela", "Dabrowski", "CAN"), ("Kaitlin", "Quevedo", "ESP"),
                   " W/O", "[1]G. Dabrowski / L. Stefani d K. Quevedo / D. Salkova  W/O",
                   "00:00:00")
PLAYED = _played("LD007", 2, "2026-09-18T16:52:43.003+00:00",
                 ("Valeriya", "Strakhova", "UKR"), ("Victoria", "Barros", "BRA"),
                 "6-2,7-5", "[2]V. Strakhova / A. Tikhonova d V. Barros / N. Leme Da Silva 6-2,7-5",
                 "01:23:00")


def test_a_walkover_has_no_start():
    wo, played = matches_for_day([WALKOVER, PLAYED], DAY, venue_tz=TZ)[::-1]
    assert (wo.time, wo.start_raw) == (None, None)
    # A match that was played keeps its real start.
    assert (played.time, played.start_raw) == ("13:52", "13:52")


def test_the_walkover_survives_the_stored_bytes():
    doc = normalize_day([WALKOVER, PLAYED], DAY, venue_tz=TZ)
    rows = json.loads(doc)
    assert all("ScoreString" not in r for r in rows)
    assert [r.get("Walkover") for r in rows] == [True, None]
    ms, _meta = parse_wta_day(doc, venue_tz=TZ)
    assert [(m.side_a[0].split()[-2], m.time) for m in ms] == [
        ("STRAKHOVA", "13:52"), ("DABROWSKI", None)]


def test_a_day_without_a_walkover_hashes_as_before():
    doc = normalize_day([PLAYED], DAY, venue_tz=TZ)
    assert b"Walkover" not in doc


def test_a_name_that_reads_wo_is_not_a_walkover():
    row = dict(PLAYED, ResultString="A. Wo d B. Smith 6-2,7-5")
    assert matches_for_day([row], DAY, venue_tz=TZ)[0].time == "13:52"
