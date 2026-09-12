"""Repairing an entry linked to the wrong Tennis Explorer player.

Two faults, both found by /issues on 2026-09-12 in a warning that had been
repeating nightly with nothing able to act on it:

  "J.J. Wolf" was reported as wrong against "Jeffrey John Wolf" — the same
  person, initialised. Twice, under two spacings.

  "Abdullah Shelbayh" really was pointing at Marton Fucsovics, because Tennis
  Explorer spells him "Abedallah" and the repair only re-pointed on an EXACT
  name. draw_odds reads te_player_id off the entry with no name check, so that
  entry was being priced with Fucsovics's Elo.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.history.link import _close_name, names_agree   # noqa: E402


class _P:
    def __init__(self, pid, name, gender='M'):
        self.id, self.gender, self.te_slug = pid, gender, name.split()[-1].lower()
        self.name_display = self.name_raw = name


def test_initials_are_the_name_they_stand_for():
    assert names_agree('J.J. Wolf', 'Jeffrey John Wolf')
    assert names_agree('J. J. Wolf', 'Jeffrey John Wolf')
    assert names_agree('J. Smith', 'John Smith')


def test_a_wrong_initial_is_still_a_different_person():
    """Alexander and Mischa Zverev share a surname and nothing else. An
    initial that does not match the given name must not pass."""
    assert not names_agree('A. Zverev', 'Mischa Zverev')
    assert not names_agree('M. Zverev', 'Alexander Zverev')


def test_initials_do_not_bridge_two_surnames():
    assert not names_agree('J.J. Wolf', 'Jeffrey John Wolfe')
    assert not names_agree('Abdullah Shelbayh', 'Marton Fucsovics')


def test_a_transliteration_is_found():
    rows = [_P(296, 'Abedallah Shelbayh'), _P(76, 'Marton Fucsovics')]
    assert [p.id for p in _close_name('Abdullah Shelbayh', 'M', rows)] == [296]


def test_sisters_are_not_each_other():
    """THE CASE THE THRESHOLD EXISTS FOR. Mirra and Erika Andreeva score 0.786
    — below the 0.85 bar — so neither is ever repaired into the other."""
    rows = [_P(2, 'Mirra Andreeva', 'F'), _P(3, 'Erika Andreeva', 'F')]
    assert [p.id for p in _close_name('Mirra Andreeva', 'F', rows)] == [2]
    assert [p.id for p in _close_name('Erika Andreeva', 'F', rows)] == [3]


def test_a_name_nothing_matches_finds_nothing():
    rows = [_P(1, 'Taylor Fritz'), _P(2, 'Marton Fucsovics')]
    assert _close_name('Someone Entirely Else', 'M', rows) == []
    assert _close_name('', 'M', rows) == []


def test_it_never_crosses_gender():
    rows = [_P(9, 'Taylor Townsend', 'F')]
    assert _close_name('Taylor Townsend', 'M', rows) == []
    assert [p.id for p in _close_name('Taylor Townsend', 'F', rows)] == [9]
