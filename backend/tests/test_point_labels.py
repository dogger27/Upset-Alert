"""Aces and double faults on the scrubber.

Matching is by ORDER inside the game, not by score: a deuce cycle revisits
40-40 and 40-A, so score alone is ambiguous, while order is not. Our snapshots
are a subsequence of theirs (the poller can miss a point, never invent one), so
a greedy two-pointer places every point exactly — including the third 40-40 of
a long deuce game."""
from app.services.sofascore_points import align, normalise

RAW = {"pointByPoint": [
    {"set": 1, "games": [
        {"game": 1, "points": [
            {"homePoint": "15", "awayPoint": "0",  "pointDescription": 1},
            {"homePoint": "15", "awayPoint": "15", "pointDescription": 0},
            {"homePoint": "40", "awayPoint": "40", "pointDescription": 0},
            {"homePoint": "40", "awayPoint": "A",  "pointDescription": 2},
            {"homePoint": "40", "awayPoint": "40", "pointDescription": 0},
        ]},
    ]},
    {"set": 2, "games": [
        {"game": 3, "points": [
            {"homePoint": "0", "awayPoint": "15", "pointDescription": 2},
        ]},
    ]},
]}


def snap(games, point):
    return {"games": games, "point": point}


def test_only_aces_and_double_faults_are_named():
    pts = normalise(RAW)
    assert pts["1-1"][0]["l"] == "Ace"
    assert pts["1-1"][3]["l"] == "Double Fault"
    assert pts["1-1"][1]["l"] is None


def test_deuce_cycle_is_resolved_by_order():
    """The score 40-40 occurs twice; order says which is which."""
    pts = normalise(RAW)
    out = align([snap([["0"], ["0"]], ["15", "0"]),
                 snap([["0"], ["0"]], ["15", "15"]),
                 snap([["0"], ["0"]], ["40", "40"]),   # their 1st 40-40
                 snap([["0"], ["0"]], ["40", "A"]),    # the double fault
                 snap([["0"], ["0"]], ["40", "40"])],  # their 2nd 40-40
                pts)
    assert out == ["Ace", None, None, "Double Fault", None]


def test_a_missed_snapshot_does_not_desync_the_rest():
    """The poller samples every 10s and can miss a point; the walk skips over
    it rather than shifting every later label by one."""
    pts = normalise(RAW)
    out = align([snap([["0"], ["0"]], ["15", "0"]),
                 # 15-15 and the first 40-40 never observed
                 snap([["0"], ["0"]], ["40", "A"]),
                 snap([["0"], ["0"]], ["40", "40"])],
                pts)
    assert out == ["Ace", "Double Fault", None]


def test_game_number_comes_from_games_played_in_the_current_set():
    # set 2, one game each = the third game of that set
    out = align([snap([["6", "1"], ["4", "1"]], ["0", "15"])], normalise(RAW))
    assert out == ["Double Fault"]


def test_orientation_is_discovered_not_assumed():
    """Snapshots are stored player1-first; Sofascore keeps its own home/away."""
    out = align([snap([["0"], ["0"]], ["0", "15"]),     # flipped 15-0
                 snap([["0"], ["0"]], ["A", "40"])],    # flipped 40-A
                normalise(RAW))
    assert out == ["Ace", "Double Fault"]


def test_missing_or_empty_inputs_are_silent():
    assert align([], {}) == []
    assert align([snap([["0"], ["0"]], ["15", "0"])], {}) == [None]
    assert align([{"games": None, "point": None}], normalise(RAW)) == [None]
    assert normalise({}) == {}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
