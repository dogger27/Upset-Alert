"""The tiebreak questions' arithmetic (owner, 2026-09-18): sets off a score
string, plausible ceilings over a record with junk in it, a player's rate per
set on a surface and against a named opponent, and the user's own finalists
read off their bracket.
"""
import sqlite3
from datetime import date
from types import SimpleNamespace as NS

from app.services.history.final_stats import ceilings, player_reference, sets_in, tour_reference
from app.routers.tournaments import predicted_finalists


def test_sets_in_reads_a_sackmann_score():
    assert sets_in("6-2 6-4") == 2
    assert sets_in("6-7(5) 7-6(3) 7-5") == 3
    assert sets_in("6-4 RET") == 1
    assert sets_in("W/O") == 0
    assert sets_in("6-3 3-6 [10-8]") == 3
    assert sets_in(None) == 0


def _db():
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE tml_matches (tour, tourney_name, tourney_date, surface, tourney_level, best_of,
                 winner_id, loser_id, winner_name, loser_name, score, minutes, w_ace, l_ace)""")
    rows = [
        # a real best-of-three ace record on the tour, and a junk row above it
        ("atp", "Halle", "20250615", "Grass", "500", 3, "A1", "B1", "Big Server", "Someone", "7-6(5) 7-6(4)", 118, 44, 9),
        ("wta", "Junk", "20240101", "Hard", "250", 3, "J1", "J2", "Bad Row", "Bad Row", "6-0 6-0", 40, 128, 0),
        ("wta", "Wimbledon", "20250701", "Grass", "G", 3, "W1", "W2", "Ace Queen", "Other", "6-4 7-6(2)", 110, 19, 3),
        # the longest plausible clay best-of-three, and a 25-hour junk row
        ("atp", "Rome", "20250512", "Clay", "M", 3, "A2", "B2", "Grinder", "Wall", "7-6(10) 6-7(8) 7-6(11)", 245, 5, 4),
        ("atp", "Junk", "20240301", "Clay", "250", 3, "J3", "J4", "Bad", "Bad", "6-4 6-4", 1531, 2, 2),
        # a Challenger row must not set a tour ceiling, but does feed a player's own rate
        ("atp", "Bergamo", "20250301", "Hard", "C", 3, "A1", "C9", "Big Server", "Kid", "6-1 6-1", 50, 21, 0),
        # the champion's history on hard in the window, and against the runner-up
        ("atp", "Cincinnati", "20250810", "Hard", "M", 3, "A1", "R1", "Big Server", "Runner", "6-4 6-4", 80, 14, 6),
        ("atp", "Miami", "20250325", "Hard", "M", 3, "R1", "A1", "Runner", "Big Server", "6-3 6-3", 70, 4, 10),
        ("atp", "Old", "20190101", "Hard", "M", 3, "A1", "R1", "Big Server", "Runner", "6-0 6-0", 45, 30, 0),   # out of the window
    ]
    c.executemany("INSERT INTO tml_matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return c


def test_ceilings_are_the_largest_plausible_values_on_the_tour():
    c = _db()
    got = ceilings(c, "atp", "Clay", 3)
    assert got["aces_max"] == 44 and got["aces_record"]["player"] == "Big Server"   # the Challenger 21 and junk excluded
    assert got["duration_max_min"] == 245 and got["duration_record"]["tournament"] == "Rome"
    wta = ceilings(c, "wta", "Grass", 3)
    assert wta["aces_max"] == 19                     # 128 is junk
    assert ceilings(c, "wta", "Clay", 3)["duration_max_min"] == 110   # no clay rows: the tour's format-wide max


def test_a_players_rate_is_per_set_on_the_surface_and_against_the_finalist():
    c = _db()
    got = player_reference(c, "atp", "A1", "Hard", "R1", today=date(2025, 9, 1))
    # Hard, window: Bergamo (21 aces, 2 sets), Cincinnati (14, 2), Miami (10 as loser, 2) -> 45 / 6
    assert got["on_surface"]["matches"] == 3 and got["on_surface"]["aces_per_set"] == 7.5
    assert got["on_surface"]["minutes_per_set"] == round(200 / 6, 1)
    # vs R1, any time: Cincinnati 14, Miami 10, Old 30 -> 54 aces over 6 sets
    assert got["vs_finalist"]["matches"] == 3 and got["vs_finalist"]["aces_per_set"] == 9.0
    assert got["overall"]["matches"] == 4      # Halle too (Rome was won by A2)


def test_the_tours_rate_counts_both_players_over_the_sets():
    c = _db()
    got = tour_reference(c, "atp", "Hard", today=date(2025, 9, 1))
    # tour levels on hard in the window: Cincinnati (14+6 over 2 sets), Miami (4+10 over 2)
    assert got["matches"] == 2 and got["aces_per_set"] == round(34 / 8, 2)


def test_the_finalists_come_off_the_users_own_bracket():
    ms = [NS(id=1, round_number=1, match_number=1), NS(id=2, round_number=1, match_number=2),
          NS(id=3, round_number=2, match_number=1)]
    assert predicted_finalists({1: 11, 2: 22, 3: 11}, ms, 2) == (11, 22)
    assert predicted_finalists({1: 11, 2: 22}, ms, 2) == (None, 22)       # no final pick yet
    assert predicted_finalists({}, ms, 2) == (None, None)


def test_every_reference_figure_stays_on_its_own_tour():
    # TennisMyLife numbers ATP and WTA players separately, and one string can
    # name a different person on each tour: the same id "7" is a WTA player
    # here and an ATP player there. Nothing about the women's draw may read
    # the men's rows, and nothing about the men's the women's (owner,
    # 2026-09-18).
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE tml_matches (tour, tourney_name, tourney_date, surface, tourney_level, best_of,
                 winner_id, loser_id, winner_name, loser_name, score, minutes, w_ace, l_ace)""")
    c.executemany("INSERT INTO tml_matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("wta", "Doha", "20250201", "Hard", "1000", 3, "7", "8", "Her", "Her Rival", "6-4 6-4", 90, 4, 2),
        ("atp", "Doha", "20250201", "Hard", "500", 3, "7", "9", "Him", "His Rival", "6-4 6-4", 80, 24, 10),
        ("atp", "Doha", "20250202", "Hard", "500", 3, "7", "9", "Him", "His Rival", "7-6(3) 7-6(5)", 120, 30, 12),
    ])
    her = player_reference(c, "wta", "7", "Hard", "8", today=date(2025, 9, 1))
    assert her["on_surface"]["matches"] == 1 and her["on_surface"]["aces_per_set"] == 2.0
    assert her["vs_finalist"]["matches"] == 1
    him = player_reference(c, "atp", "7", "Hard", "9", today=date(2025, 9, 1))
    assert him["on_surface"]["matches"] == 2 and him["on_surface"]["aces_per_set"] == 13.5
    assert tour_reference(c, "wta", "Hard", today=date(2025, 9, 1))["aces_per_set"] == 1.5     # (4+2)/4 sets
    assert tour_reference(c, "atp", "Hard", today=date(2025, 9, 1))["matches"] == 2
    assert ceilings(c, "wta", "Hard", 3)["aces_max"] == 4 and ceilings(c, "atp", "Hard", 3)["aces_max"] == 30
