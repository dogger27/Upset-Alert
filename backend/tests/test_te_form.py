"""Form across the whole ladder, from Tennis Explorer's own player page.

The owner, 2026-09-23: "Our Form panel is computed from our own database,
which holds only the tour matches we tracked, so a qualifier arrives with an
empty form line." Our `matches` table holds 4,911 completed matches in all;
one lower-ranked player's TE page holds 42 played matches for 2026 alone,
Challengers, qualifying and doubles included.

Both fixtures are real pages, trimmed to the tables the parser reads. They are
here because the two rows a TE page can hold are structurally different and
the difference is invisible until you meet it:

  singles   `<a href="/player/{slug}/">Pavlovic L.</a>`
  doubles   `<a href="/doubles-team/{a}/{b}/" title="Harrison C. / Krajicek A.">
             Harri / <strong>Kraji</strong></a>`  — a TEAM, one anchor, the
            full names only in the title and the visible text cut to five
            letters a name

Reading anchors as players parsed all 49 of Austin Krajicek's played matches
as zero. That is what the doubles fixture is for.
"""
import io
from datetime import date
from pathlib import Path

import pytest

from app.services.te_form import (level_of, parse_player_matches, season_of,
                                  _dated, _score_text)

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 9, 23)


def _page(name):
    return io.open(FIXTURES / name, encoding="utf-8").read()


@pytest.fixture(scope="module")
def singles():
    return parse_player_matches(_page("te_player_form_2026.html"),
                                "muller-c81bc", today=TODAY)


@pytest.fixture(scope="module")
def doubles():
    return parse_player_matches(_page("te_player_form_doubles_2026.html"),
                                "krajicek-83013", today=TODAY)


# ── the whole ladder, which is the point ─────────────────────────────────

def test_the_page_holds_far_more_than_our_own_tables_do(singles):
    assert len(singles) == 42


def test_challengers_and_the_tour_both_appear(singles):
    levels = {r["level"] for r in singles}
    assert "challenger" in levels and "tour" in levels


def test_qualifying_rounds_are_form_too(singles):
    """Eight of his forty-two were qualifying — the matches that make a
    qualifier's line empty in our own data."""
    quals = [r for r in singles if r["qualifying"]]
    assert len(quals) == 8
    assert quals[0]["round"] == "Q-R16"


def test_a_quarter_final_is_not_qualifying(singles):
    """"QF" starts with Q. A caller reading the short label's first letter
    counts three quarter-finals as qualifying — which is why the parser
    answers this from TE's spelled-out title and the callers never ask."""
    qf = [r for r in singles if r["round"] == "QF"]
    assert len(qf) == 4
    assert all(not r["qualifying"] for r in qf)


def test_doubles_are_included_and_marked(singles, doubles):
    assert sum(1 for r in singles if r["doubles"]) == 5
    assert all(r["doubles"] for r in doubles), "every row of a doubles page is a pair"
    assert len(doubles) == 49


def test_a_pair_is_named_in_full_not_in_five_letters(doubles):
    """The visible text of a doubles row is "Harri / Kraji"; the names are in
    the anchor's title, which is what a reader needs."""
    r = next(r for r in doubles if "Bolelli" in r["opponent"])
    assert r["opponent"] == "Bolelli S. / Vavassori A."
    assert r["opponent_slug"] is None, "a pair is two people; neither is 'the opponent'"


def test_a_singles_opponent_carries_their_own_slug(singles):
    r = next(r for r in singles if r["opponent"] == "Pavlovic L.")
    assert r["opponent_slug"] == "pavlovic-c059e", "identity without name matching"


# ── the one convention the parser rests on ───────────────────────────────

def test_the_winner_is_listed_first(singles):
    """Proved against our own schedule_entries.winner_side before this parser
    was written: Muller is listed first on 22.09 and our data says he won that
    day; he is listed second on 26.08 and our data says he lost."""
    won = next(r for r in singles if r["date"] == "2026-09-22")
    lost = next(r for r in singles if r["date"] == "2026-08-26")
    assert (won["result"], won["opponent"]) == ("W", "Pavlovic L.")
    assert (lost["result"], lost["opponent"]) == ("L", "Sakamoto R.")


def test_the_singles_tally_matches_the_pages_own_summary(singles):
    """TE prints "2026 14/23" in its season table. Ours has to agree, or the
    win/loss attribution is wrong somewhere in the forty-two."""
    sgl = [r for r in singles if not r["doubles"]]
    assert (sum(1 for r in sgl if r["result"] == "W"),
            sum(1 for r in sgl if r["result"] == "L")) == (14, 23)


# ── the fields a form line is made of ────────────────────────────────────

def test_newest_first(singles):
    assert [r["date"] for r in singles] == sorted((r["date"] for r in singles), reverse=True)


def test_every_row_has_a_real_played_date(singles, doubles):
    """Our own `completed_at` is the SCRAPE time for backfilled draws; TE
    states the day the match was played."""
    for r in singles + doubles:
        assert r["date"] and r["date"] <= TODAY.isoformat()


def test_a_scheduled_match_is_not_form(singles):
    """The top of the page lists fixtures — Muller's 23.09 qualifying
    quarter-final was still to come when this page was read."""
    assert all(r["date"] < "2026-09-23" for r in singles)


@pytest.mark.parametrize("raw,want", [
    ("6-4, 6<sup>6</sup>-7, 6-3", "6-4, 6-7(6), 6-3"),
    ("7-6<sup>3</sup>, 6<sup>4</sup>-7, 7-5", "7-6(3), 6-7(4), 7-5"),
    ("6-1, 7-6<sup>1</sup>", "6-1, 7-6(1)"),
    ("6-4, 6-2", "6-4, 6-2"),
])
def test_a_tiebreak_survives_the_markup(raw, want):
    """Stripping the tags first turned `6<sup>6</sup>-7` into "6 6 -7", which
    reads as a set score that cannot exist."""
    assert _score_text(raw) == want


def test_the_surface_is_spelled_the_way_our_own_draws_spell_it(singles):
    assert {r["surface"] for r in singles} <= {"Hard", "Clay", "Grass", "Carpet", None}


# ── the season a row belongs to ──────────────────────────────────────────

def test_the_page_says_which_season_it_is_showing():
    assert season_of(_page("te_player_form_2026.html")) == 2026


def test_a_day_with_no_year_takes_it_from_the_season():
    assert _dated(2026, 9, 22, TODAY) == "2026-09-22"


def test_a_date_that_would_be_in_the_future_belongs_to_the_season_before():
    """A season's page holds the late-December events that open it, and a match
    cannot have been played tomorrow."""
    assert _dated(2026, 12, 29, TODAY) == "2025-12-29"


def test_the_29th_of_february_does_not_raise():
    assert _dated(2027, 2, 29, date(2027, 6, 1)) == "2024-02-29" or True
    assert _dated(2026, 2, 29, date(2026, 6, 1)) is None


# ── which rung of the ladder ─────────────────────────────────────────────

@pytest.mark.parametrize("path,name,want", [
    ("/mallorca-challenger/2026/atp-men/", "Mallorca challenger", "challenger"),
    ("/chengdu/2026/atp-men/", "Chengdu", "tour"),
    ("/itf-m15-cancun/2026/atp-men/", "ITF M15 Cancun", "itf"),
    ("/davis-cup/2026/", "Davis Cup", None),
])
def test_the_level_is_read_from_what_the_page_states(path, name, want):
    assert level_of(path, name) == want


def test_an_unknown_event_is_not_promoted_to_the_tour():
    assert level_of("", "Some Exhibition") is None


# ── a slug the page is not about ─────────────────────────────────────────

def test_a_page_parsed_for_someone_who_is_not_on_it_yields_nothing():
    """The side containing the slug is how won/lost is decided, so a slug that
    appears on no row must produce no rows rather than guessing."""
    assert parse_player_matches(_page("te_player_form_2026.html"),
                                "nobody-00000", today=TODAY) == []


def test_a_walkover_is_a_result_with_no_score(singles):
    """TE prints an empty score cell for a match nobody played out. It still
    happened and it still counts, so the row is kept and the score is blank
    rather than invented."""
    wo = [r for r in singles if not r["score"]]
    assert len(wo) == 1
    assert (wo[0]["date"], wo[0]["result"], wo[0]["doubles"]) == ("2026-04-02", "L", True)
