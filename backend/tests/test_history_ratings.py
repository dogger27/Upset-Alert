"""The chronological Elo: what it must and must not do."""
from app.services.history.ratings import Ratings, played, walk


def _row(tour, tid, date, surface, level, rnd, num, w, l, score="6-3 6-4", bo=3, src="tml"):
    return (tour, tid, date, surface, level, rnd, num, w, l, score, bo, src)


def test_a_walkover_moves_nothing_and_a_retirement_counts():
    assert not played("W/O") and not played("w/o") and not played("DEF")
    assert played("6-3 1-0 RET") and played("6-4 6-4")
    rows = [_row("atp", "t1", "2026-01-05", "Hard", "250", "R32", 1, "A", "B", score="W/O")]
    for _ in walk(rows, {"k0": 250, "k_decay": 0.4, "k_offset": 5, "level_k": {}}):
        pass
    assert walk.final.elo == {}


def test_the_winner_goes_up_the_loser_down_by_the_same_amount():
    rows = [_row("atp", "t1", "2026-01-05", "Clay", "250", "R32", 1, "A", "B")]
    for r, pre_w, pre_l in walk(rows, {"k0": 250, "k_decay": 0.4, "k_offset": 5, "level_k": {}}):
        # (overall, surface, matches, surface matches, days since last played)
        assert pre_w == (1500.0, 1500.0, 0, 0, None) and pre_l == (1500.0, 1500.0, 0, 0, None)
    st = walk.final
    assert st.elo[("atp", "A")] > 1500 > st.elo[("atp", "B")]
    assert abs((st.elo[("atp", "A")] - 1500) - (1500 - st.elo[("atp", "B")])) < 1e-9
    # The surface rating moved on clay and only on clay.
    assert st.selo[("atp", "A")]["Clay"] > 1500 and "Hard" not in st.selo[("atp", "A")]


def test_k_decays_with_matches_played():
    st = Ratings({"k0": 250, "k_decay": 0.4, "k_offset": 5, "level_k": {}})
    assert st.k(0, None) > st.k(10, None) > st.k(100, None) > 0
    assert st.k(0, "G") == st.k(0, None)                       # no level multiplier unless asked
    st2 = Ratings({"k0": 250, "k_decay": 0.4, "k_offset": 5, "level_k": {"G": 1.5}})
    assert st2.k(0, "G") == 1.5 * st2.k(0, "250")


def test_tours_are_separate_worlds_and_pre_match_state_is_pre_match():
    rows = [_row("atp", "t1", "2026-01-05", "Hard", "250", "R32", 1, "A", "B"),
            _row("wta", "w1", "2026-01-05", "Hard", "250", "R32", 1, "A", "B"),
            _row("atp", "t1", "2026-01-05", "Hard", "250", "R16", 2, "A", "C")]
    seen = list(walk(rows, {"k0": 250, "k_decay": 0.4, "k_offset": 5, "level_k": {}}))
    # The second ATP match sees A's rating AFTER the first — and the WTA "A" is somebody else.
    assert seen[2][1][0] > 1500 and seen[2][1][2] == 1
    # The WTA "A" has one win; the ATP "A" had exactly that rating before its second match.
    assert walk.final.elo[("wta", "A")] == seen[2][1][0]
    assert walk.final.n[("atp", "A")] == 2 and walk.final.n[("wta", "A")] == 1


def test_the_walk_reports_how_long_a_player_has_been_away():
    """A rating cannot see time; the pass hands the caller the gap so a model
    can decide whether eight months off should cost anything."""
    rows = [_row("atp", "t1", "2026-01-05", "Hard", "250", "R32", 1, "A", "B"),
            _row("atp", "t2", "2026-01-12", "Hard", "250", "R32", 1, "A", "C"),
            _row("atp", "t3", "2026-09-01", "Hard", "250", "R32", 1, "A", "D")]
    seen = list(walk(rows, {"k0": 250, "k_decay": 0.4, "k_offset": 5, "level_k": {}}))
    assert seen[0][1][4] is None          # a debut has no gap
    assert seen[1][1][4] == 7             # a week later
    assert seen[2][1][4] == 232           # and then a long time off
    assert seen[2][2][4] is None          # D is the debutant in that one
