"""A result needs a score, and a bye needs to be in round one.

Guadalajara 2026 (draw 142): two quarter-finals were "won" before being
played. One occupant in an RD3 cell with a blank opposite was read as a bye —
the draw is 28 in a 32 bracket, so byes were possible, and the lone-occupant
rule was not gated to round one. Two more had a bold name and no score, and
the apply step took the bold as a result. Both invariants live here now.
"""
from types import SimpleNamespace

from app.routers.tournaments import _clear_phantom, _wikipedia_may_decide
from app.services.scraper import _parse_16team_section


def _section_28_in_32_with_unplayed_qf() -> dict[str, str]:
    """A 16-team section of a 28-draw: a real R1 bye, one played R1 match, a
    played R2 match, and an RD3 occupant carried forward with nobody opposite."""
    p: dict[str, str] = {}
    # Seed 1 sits straight in RD2 with both RD1 slots blank: a genuine bye.
    p["RD2-team01"] = "'''[[Seed One]]'''"
    p["RD2-seed01"] = "1"
    # Slots 3-4: a played first-round match.
    p["RD1-team03"] = "'''[[Alice Winner]]'''"
    p["RD1-team04"] = "[[Bob Loser]]"
    p["RD1-score03-1"], p["RD1-score04-1"] = "6", "3"
    p["RD1-score03-2"], p["RD1-score04-2"] = "6", "4"
    # RD2: the seed beat Alice, with a score.
    p["RD2-team02"] = "[[Alice Winner]]"
    p["RD2-score01-1"], p["RD2-score02-1"] = "6", "2"
    p["RD2-score01-2"], p["RD2-score02-2"] = "6", "2"
    # RD3: the seed carried forward, NOT bold, NO score, and nobody opposite
    # because the other R2 feeder has not been played (RD2 slots 3-4 blank).
    p["RD3-team01"] = "[[Seed One]]"
    return p


def _parse(params):
    players, matches = [], []
    _parse_16team_section(params, section_index=0, global_round_offset=1,
                          players_out=players, matches_out=matches,
                          draw_size=28, include_section_final=True, byes_allowed=True)
    by_key = {(m.round_number, m.match_number): m for m in matches}
    return by_key


def test_lone_occupant_past_round_one_is_pending_not_a_bye():
    m = _parse(_section_28_in_32_with_unplayed_qf())
    qf = m[(3, 1)]
    assert qf.is_bye is False, "a bye cannot exist after round one"
    assert qf.winner_position is None, "nobody has won a match that has not been played"
    assert qf.scores is None


def test_a_real_first_round_bye_still_advances():
    # The gate must not over-correct: the seed's bye is still a bye.
    m = _parse(_section_28_in_32_with_unplayed_qf())
    r1 = m[(1, 1)]
    assert r1.is_bye is True
    assert r1.winner_position == 1, "the bye seed takes the pair's first position"
    # And the seed's scored R2 win is still a result.
    r2 = m[(2, 1)]
    assert r2.winner_position == 1
    assert r2.scores == [["6", "6"], ["2", "2"]]


def _match(**kw):
    base = dict(winner_id=None, sofa_winner_id=None, scores_json=None,
                status="pending", completed_at=None, live_scores_json=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_clear_phantom_undoes_a_scoreless_unbacked_winner():
    m = _match(winner_id=5901, status="completed", completed_at="t", scores_json=None)
    assert _clear_phantom(m) is True, "reports that it acted"
    assert m.winner_id is None and m.status == "pending" and m.completed_at is None


def test_clear_phantom_leaves_real_results_alone():
    # A score of any shape is a real outcome — sets, a walkover, a retirement.
    for scores in ([["6", "6"], ["3", "4"]], [["w/o"], [""]], [["3r"], ["5"]]):
        m = _match(winner_id=1, status="completed", scores_json=scores)
        assert _clear_phantom(m) is False
        assert m.winner_id == 1, f"cleared a real result with scores {scores}"
    # Sofascore's word is enough on its own, even with no score stored yet.
    m = _match(winner_id=1, sofa_winner_id=1, status="completed", scores_json=None)
    _clear_phantom(m)
    assert m.winner_id == 1
    # And a row with nothing stored is untouched.
    m = _match()
    _clear_phantom(m)
    assert m.winner_id is None and m.status == "pending"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)


# ---- THE RULE: Wikipedia never decides a result ---------------------------
def _mr(**kw):
    base = dict(round_number=3, match_number=1, player1_position=1, player2_position=2,
                winner_position=1, is_bye=False, scores=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_wikipedia_never_decides_a_result_even_with_a_full_score():
    # Bold winner AND a complete score on the sheet: still not a result.
    # "NEVER, EVER, use Wikipedia for a match result or score" (owner, 2026-09-16).
    assert _wikipedia_may_decide(_mr(scores=[["6", "6"], ["3", "4"]])) is False
    assert _wikipedia_may_decide(_mr(scores=[["w/o"], [""]])) is False
    assert _wikipedia_may_decide(_mr(scores=None)) is False


def test_the_one_exception_is_a_first_round_bye():
    # A bye is draw shape: nobody was placed opposite, so there is no match
    # for Sofascore or ESPN to ever report.
    assert _wikipedia_may_decide(_mr(round_number=1, is_bye=True, winner_position=1)) is True
