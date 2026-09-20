"""The short name an event gets before anybody sets one.

The rule is the owner's: the tournament's name with the word "Open" taken out
(2026-09-20). The cases below are real names out of the production database —
all seventy-one events whose name carries the word were checked, and the two
that come out as two letters are in here because they are the interesting
ones, not because they are wrong.
"""
import pytest

from app.models.tournament import default_short_name


@pytest.mark.parametrize("name, short", [
    # The ordinary shape, which is almost all of them.
    ("Korea Open", "Korea"),
    ("Guadalajara Open", "Guadalajara"),
    ("Winston-Salem Open", "Winston-Salem"),
    ("Swedish Open", "Swedish"),
    # THE WORD CAN LEAD, in which case a French connector is left behind and
    # comes off too: "de Rouen" is not a name, "Rouen" is.
    ("Open de Rouen", "Rouen"),
    ("Open Occitanie", "Occitanie"),
    # ...but only at the front. "Sud" is capitalised and stays, and so does
    # the "de" inside it.
    ("Open Sud de France", "Sud de France"),
    # Two letters is a real short form for these two, and both are what a
    # chip would say.
    ("US Open", "US"),
    ("SP Open", "SP"),
    # No "Open" in the name: nothing to take out, and nothing invented.
    ("Roland Garros", "Roland Garros"),
    ("Nitto ATP Finals", "Nitto ATP Finals"),
    ("Wimbledon", "Wimbledon"),
])
def test_the_word_comes_out(name, short):
    assert default_short_name(name) == short


@pytest.mark.parametrize("name", ["Open", "open", "  Open  ", "Opens"])
def test_a_name_that_is_only_the_word_keeps_it(name):
    """A short name still has to be a name.

    Stripping here leaves nothing at all, so the full name stands rather than
    an empty chip — the same instinct as the name ladder's: shorten, never
    erase.
    """
    assert default_short_name(name) == name.strip()


def test_nothing_in_nothing_out():
    assert default_short_name("") == ""
    assert default_short_name(None) == ""


def test_the_word_is_matched_whole():
    """"Open" inside another word is part of that word."""
    assert default_short_name("Opening Week Classic") == "Opening Week Classic"
    assert default_short_name("Copenhagen Championship") == "Copenhagen Championship"
