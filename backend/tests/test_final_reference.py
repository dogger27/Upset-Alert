"""THE THREE QUESTIONS' REFERENCE FIGURES (owner, 2026-09-19).

Every figure is conditioned on the draw: tour, tier, surface, and the two
players the bracket picked. The tier vocabularies do not match between our
draws and Sackmann's file, and that mapping is where this can quietly answer
a WTA 250 with someone else's numbers.
"""
import sqlite3
from datetime import date
from types import SimpleNamespace as NS

from app.services import final_reference
from app.services.history.final_stats import (
    BETWEEN_SETS_SECONDS, TIER_LEVELS, estimate_minutes, h2h_set_minutes,
    h2h_sets, player_rates, tier_finals,
)

TODAY = date(2026, 6, 1)


def _db():
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE tml_matches (tour, tourney_name, tourney_date, surface, tourney_level,
                 round, best_of, winner_id, loser_id, winner_name, loser_name, score, minutes,
                 w_ace, l_ace)""")
    rows = [
        # Two WTA 250 finals on hard, inside every window.
        ("wta", "Seoul", "2025-09-21", "Hard", "250", "F", 3, "A", "B", "Champ", "Rival",
         "6-4 6-3", 90, 5, 3),
        ("wta", "Hobart", "2026-01-11", "Hard", "250", "F", 3, "B", "A", "Rival", "Champ",
         "7-6(3) 4-6 6-2", 150, 4, 6),
        # THE WTA'S OLD NAME FOR THE SAME TIER. 'I' was International, which
        # became the 250 — a decade of finals spans the rename, and dropping it
        # would halve the sample.
        ("wta", "Linz", "2019-10-13", "Hard", "I", "F", 3, "A", "C", "Champ", "Someone",
         "6-2 6-2", 70, 2, 1),
        # A SEMI-FINAL, not a final: the questions are about a final.
        ("wta", "Seoul", "2025-09-20", "Hard", "250", "SF", 3, "A", "D", "Champ", "Else",
         "6-0 6-0 6-0", 200, 30, 0),
        # Another tour, another tier, another surface — none of it may leak in.
        ("atp", "Rome", "2025-05-18", "Clay", "M", "F", 3, "X", "Y", "Him", "Other",
         "6-4 6-4", 100, 9, 8),
    ]
    c.executemany("INSERT INTO tml_matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return c


def test_a_tier_reads_its_own_finals_including_the_tours_old_name_for_it():
    got = tier_finals(_db(), "wta", "250", "Hard", 10, TODAY)
    assert got["matches"] == 3, "two 250s and the International, not the semi-final"
    assert got["surface_scoped"] is True
    # (2 + 3 + 2) / 3 sets
    assert got["sets_per_match"] == 2.33


def test_a_shorter_window_drops_the_older_final():
    got = tier_finals(_db(), "wta", "250", "Hard", 5, TODAY)
    assert got["matches"] == 2, "2019 is outside five years"


def test_a_surface_the_tier_never_played_falls_back_and_says_so():
    got = tier_finals(_db(), "wta", "250", "Grass", 10, TODAY)
    assert got["matches"] == 3 and got["surface_scoped"] is False


def test_the_tier_map_never_crosses_tours():
    # 'M' is the ATP's 1000; asking the WTA for a 1000 must not find it.
    assert "M" not in TIER_LEVELS["wta"]["1000"]
    assert tier_finals(_db(), "wta", "1000", "Clay", 10, TODAY) is None
    # …and an unknown tier is None rather than everything.
    assert tier_finals(_db(), "wta", "nonsense", "Hard", 10, TODAY) is None


def test_a_players_aces_follow_the_player_not_the_result():
    c = _db()
    got = player_rates(c, "wta", "A", "Hard", 10, today=TODAY)
    # Champ won Seoul (5 aces / 2 sets), LOST Hobart (6 / 3), won Linz (2 / 2),
    # won the semi-final (30 / 3). Reading w_ace throughout would credit
    # Champ with Rival's 4 from Hobart.
    assert got["matches"] == 4
    assert got["aces_per_set"] == round((5 + 6 + 2 + 30) / 10, 2)


def test_a_head_to_head_is_narrowed_to_the_two_of_them():
    c = _db()
    got = player_rates(c, "wta", "A", "Hard", 10, opponent_tml_id="B", today=TODAY)
    assert got["matches"] == 2, "Linz and the semi-final were against other people"


def test_h2h_sets_counts_the_surface_and_what_is_elsewhere():
    c = _db()
    c.execute("INSERT INTO tml_matches VALUES "
              "('wta','Madrid','2024-05-01','Clay','1000','QF',3,'A','B','Champ','Rival','6-1 6-1',60,1,1)")
    got = h2h_sets(c, "wta", "A", "B", "Hard")
    assert got["on_surface"]["matches"] == 2
    # off_surface is what makes an "all surfaces" row worth showing at all: it
    # is 0 when that row would just repeat the surface one.
    assert got["off_surface"] == 1 and got["overall"]["matches"] == 3
    assert h2h_sets(c, "wta", "A", "B", "Clay")["off_surface"] == 2
    assert h2h_sets(c, "wta", "A", "Z", "Hard")["on_surface"] is None


def test_the_h2h_duration_estimate_adds_a_changeover_between_sets():
    c = _db()
    per = h2h_set_minutes(c, "wta", "A", "B", "Hard")
    # (90 + 150) minutes over (2 + 3) sets
    assert per["minutes_per_set"] == 48.0
    gap = BETWEEN_SETS_SECONDS / 60
    assert estimate_minutes(48.0, 2) == round(48 * 2 + gap)
    assert estimate_minutes(48.0, 3) == round(48 * 3 + gap * 2)
    # A two-set final gets one changeover, not two — and nothing without data.
    assert estimate_minutes(None, 3) is None and estimate_minutes(48.0, 0) is None


# ── The cached draw-level block ──────────────────────────────────────────────

def _draw(**kw):
    fields = {"id": 1, "gender": "F", "surface": "Hard", "category": "WTA 250",
              "status": "upcoming", "final_ref_json": None, "draw_size": 32}
    fields.update(kw)
    d = NS(**fields)
    # scoring_tier is a property on the real model, so the stand-in sets it.
    d.scoring_tier = "250"
    return d


def test_the_cached_block_carries_its_conditions_and_the_minutes_per_length():
    got = final_reference.compute(_db(), "wta", "250", "Hard", 3, TODAY)
    assert got["tour"] == "wta" and got["tier"] == "250" and got["surface"] == "Hard"
    assert got["sets"]["matches"] == 3 and got["rates"]["matches"] == 2
    # A best-of-three final is two or three sets — never four.
    assert set(got["minutes_by_sets"]) == {"2", "3"}
    per = got["rates"]["minutes_per_set"]
    assert got["minutes_by_sets"]["2"] == int(round(per * 2))
    assert final_reference.compute(_db(), "atp", "1000", "Clay", 5, TODAY)["minutes_by_sets"] is not None


def test_a_block_is_stale_when_the_draw_it_describes_has_changed():
    """A draw's surface and category are seeded from a season page and get
    corrected, so the figures have to follow — or a clay 250 keeps answering
    with hard-court numbers."""
    block = final_reference.compute(_db(), "wta", "250", "Hard", 3, TODAY)
    d = _draw(final_ref_json=block)
    assert final_reference._stale(block, d) is False
    d.surface = "Clay"
    assert final_reference._stale(block, d) is True
    d.surface = "Hard"
    d.scoring_tier = "500"
    assert final_reference._stale(block, d) is True
    # Missing, junk, and a block from an older shape all need recomputing.
    assert final_reference._stale(None, _draw()) is True
    assert final_reference._stale({"version": 0}, _draw()) is True
    assert final_reference._stale("not a dict", _draw()) is True
