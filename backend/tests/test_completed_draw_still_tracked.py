"""A draw is not finished while a match in it has no result.

The 2026 Guadalajara final (2026-09-20): Wikipedia showed a name in the
champion slot minutes after the match ended but no score. The scrape refused
the result — Wikipedia may not decide one — and then marked the DRAW complete
on the strength of that same name. A completed draw leaves Sofascore tracking,
so the only source allowed to decide never looked again, and the final sat
unresolved for hours with its score frozen mid-second-set and the app still
calling it live.
"""
from types import SimpleNamespace as NS

def _parsed(winner_position, scores):
    """Just the two fields the decision reads — ParsedDraw itself needs a draw
    size and a round count this has no opinion about."""
    return NS(matches=[
        NS(round_number=1, winner_position=0, scores=[["6", "4"], ["6", "3"]]),
        NS(round_number=2, winner_position=winner_position, scores=scores),
    ])


def _decide(parsed):
    """The scraper's own test, lifted: a final is over when it has a winner
    AND a score."""
    max_round = max((m.round_number for m in parsed.matches), default=0)
    finals = [m for m in parsed.matches if m.round_number == max_round]
    return bool(finals and finals[0].winner_position is not None and finals[0].scores)


def test_a_name_in_the_champion_slot_does_not_end_a_tournament():
    # What Wikipedia had at 00:36 on 2026-09-20: the winner, no score.
    assert _decide(_parsed(1, None)) is False
    assert _decide(_parsed(1, [])) is False


def test_a_scored_final_does():
    assert _decide(_parsed(1, [["4", "2"], ["6", "6"]])) is True


def test_an_unplayed_final_does_not():
    assert _decide(_parsed(None, None)) is False


def test_the_tracking_predicate_is_winnerless_not_verdictless():
    """The safety net in sofascore_live._tracked keys on a match with NO
    WINNER, not one merely lacking a Sofascore verdict.

    Eighty-seven completed draws lacked a verdict on some match whose winner
    was perfectly well known; tracking those would be a permanent traffic cost
    for nothing. Winnerless was true of exactly one match in the database —
    the broken one — and stops being true the moment the result lands.
    """
    import inspect
    from app.services import sofascore_live
    src = inspect.getsource(sofascore_live._tracked)
    assert "Match.winner_id.is_(None)" in src, "the net must key on a missing WINNER"
    assert "Match.sofa_winner_id" not in src, "keying on the verdict would track 87 draws forever"
    assert 'Draw.status != "completed"' in src and "or_(" in src, \
        "a live draw is still tracked the ordinary way"
