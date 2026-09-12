"""The chances must be shown only when they mean something, and must go stale
the moment anything they depend on moves.

Owner's rule, 2026-09-12: not until the picks are locked — a chance computed
over brackets people are still editing is a number about a field that does not
exist yet. And when they ARE shown, they must follow a completed match, a
player replaced in the draw, a withdrawal, an edited pick.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.scoring import chances_fingerprint, chances_history_key   # noqa: E402


def field(*rows):
    """(id, p1, p2, winner, bye) per match."""
    return [SimpleNamespace(id=i, draw_id=9, player1_id=a, player2_id=b,
                            winner_id=w, is_bye=bye) for i, a, b, w, bye in rows]


BASE = field((1, 10, 11, None, False), (2, 12, 13, None, False))
PICKS = {1: {1: 10, 2: 12}}


def fp(matches=None, picks=None, odds=None):
    return chances_fingerprint(matches or BASE, 5, picks or PICKS, odds)


def test_the_same_state_is_the_same_version():
    assert fp() == fp()


def test_a_completed_match_changes_it():
    played = field((1, 10, 11, 10, False), (2, 12, 13, None, False))
    assert fp(played) != fp()


def test_a_replaced_player_changes_it():
    """The case the old key missed entirely: the draw id, the picks and the
    odds key are all unchanged when one entry becomes another, so a stored map
    would have been served for a field that had moved."""
    replaced = field((1, 10, 99, None, False), (2, 12, 13, None, False))
    assert fp(replaced) != fp()


def test_a_withdrawal_before_the_match_changes_it():
    """A walkover turns a contest into a decided match — a winner and, where
    the sheet says so, a bye."""
    walkover = field((1, 10, 11, 10, True), (2, 12, 13, None, False))
    assert fp(walkover) != fp()


def test_an_edited_pick_changes_it():
    assert fp(picks={1: {1: 11, 2: 12}}) != fp()
    assert fp(picks={1: {1: 10, 2: 12}, 2: {1: 10}}) != fp()


def test_a_new_rating_week_changes_it():
    """`odds.cache_key` carries MODEL_VERSION, the ranking week and
    ratings_as_of, so a nightly recompute makes every answer new."""
    a = SimpleNamespace(cache_key=(4, 9, '2026-08-31', '2026-09-12'))
    b = SimpleNamespace(cache_key=(4, 9, '2026-08-31', '2026-09-13'))
    assert fp(odds=a) != fp(odds=b)


def test_the_history_key_carries_the_field():
    """chances_history_key keys the map handed to the client. Without the
    field in it, a replacement left the previous map in place."""
    k1 = chances_history_key(9, 5, PICKS, None, BASE)
    k2 = chances_history_key(9, 5, PICKS, None,
                             field((1, 10, 99, None, False), (2, 12, 13, None, False)))
    assert k1 != k2
