"""The other side of an already-linked schedule row.

A row held its bracket match with one player unlinked — the sheet's
"Aleksandr SHEVCHENKO" never folded onto the draw's "Alexander Shevchenko" —
and nothing revisited it, so he showed with no seed, no rank and the sheet's
spelling (US Open 2026-08-30; owner, 2026-09-17). The match itself says who
he is; the surname is the guard against a substitute.
"""
from app.services.schedule import surname_agrees


def test_a_transliterated_given_name_still_agrees_on_the_surname():
    assert surname_agrees("Aleksandr SHEVCHENKO", "Alexander Shevchenko")
    assert surname_agrees("A. SHEVCHENKO", "Alexander Shevchenko")
    assert surname_agrees("Adolfo Daniel VALLEJO", "Adolfo Daniel Vallejo")


def test_accents_fold_away():
    assert surname_agrees("Dino PRIZMIC", "Dino Prižmić")
    assert surname_agrees("Gael MONFILS", "Gaël Monfils")


def test_a_different_surname_is_a_different_player():
    assert not surname_agrees("Aleksandr SHEVCHENKO", "Gaël Monfils")
    assert not surname_agrees("", "Alexander Shevchenko")
    assert not surname_agrees("Lucky LOSER", "")
