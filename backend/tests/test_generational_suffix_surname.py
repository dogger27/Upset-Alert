"""A generational suffix is furniture, not a surname.

Chengdu 2026-09-23, 10:00 UTC. The ATP feed printed the R32 slot "Martin Damm
Jr" (its nationality carried in its own column, so the name held no capitals
at all) against "Shintaro Mochizuki". Every surname reading in the codebase
falls back to the LAST TOKEN when a name shouts no surname, so all five of
them read this player's surname as "jr":

    carry_surname                 schedule.py       -> 'jr'
    _sheet_surnames               sofascore_doubles -> {'jr'}
    _sheet_people                 sofascore_doubles -> 'jr'
    _surname_readings             schedule.py       -> {'jr', 'martin'}
    _surname                      schedule_feeds    -> 'jr'
    _pairing_surname (the LAW's)  schedule_invariants -> 'jr'

So `surname_agrees("Martin Damm Jr", "Martin Damm")` was False,
`stamp_linked_rows` refused to link a slot whose OWN bracket match already
named him, the card lost his seed, rank, nationality and profile link, and
`bracket_player_unlinked` alerted — the law's own `_person_words` reading
being the one that saw through it, which is exactly what that law is for.

The country code taught this lesson once already (`carry_surname`'s docstring:
"THE LAST TOKEN OF A SHEET NAME IS THE COUNTRY, NOT THE SURNAME"). A
generational suffix is the same class of furniture and is stripped the same
way. Measured over the whole stored corpus on 2026-09-23 — 1,206 distinct
schedule names, 598 draw entries, 184 Sofascore spellings, 1,828 distinct
strings in all — exactly ONE reading changes, and it is Damm's.
"""
import pytest

from app.services.schedule import (carry_surname, _surname_readings,
                                   join_surnames, surname_agrees)
from app.services.schedule_feeds import _surname as _feed_surname
from app.services.schedule_invariants import _GEN_SUFFIX_RE
from app.services.sofascore_doubles import (_sheet_people, _sheet_surnames,
                                            strip_gen_suffix)

# Every shape the two tours could print the same man in.
DAMM = [
    "Martin Damm Jr",        # the ATP feed, 2026-09-23 — what actually broke
    "Martin Damm Jr.",
    "Martin DAMM Jr USA",    # a sheet that signs the country
    "Martin DAMM JR USA",
    "[Q] Martin Damm Jr",
]


@pytest.mark.parametrize("raw", DAMM)
def test_every_reading_calls_him_damm(raw):
    assert carry_surname(raw) == "damm", raw
    assert _sheet_surnames([raw]) == {"damm"}, raw
    assert [p.surname for p in _sheet_people([raw])] == ["damm"], raw
    assert join_surnames([raw]) == frozenset({"damm"}), raw
    assert _feed_surname(raw) == "damm", raw
    assert "damm" in _surname_readings(raw), raw
    assert "jr" not in _surname_readings(raw), raw


def test_the_feed_name_agrees_with_the_draws():
    """The link `stamp_linked_rows` could not make (Chengdu, entry 6043)."""
    assert surname_agrees("Martin Damm Jr", "Martin Damm")
    assert surname_agrees("Martin DAMM Jr USA", "Martin Damm")


def test_a_different_surname_still_disagrees():
    """The suffix is forgiven; the surname is not. A substitute must not link."""
    assert not surname_agrees("Martin Damm Jr", "Martin Klizan")
    assert not surname_agrees("Sebastian Korda Jr", "Martin Damm")


def test_the_law_reads_a_suffix_the_same_way():
    """schedule_invariants keeps its own copy on purpose (see `_person_words`),
    so it has to be tested on its own terms."""
    for tok in ("Jr", "JR", "jr.", "Jnr", "Sr", "Snr", "II", "III", "IV"):
        assert _GEN_SUFFIX_RE.match(tok), tok
    for tok in ("Damm", "Ma", "Te", "Wu", "USA", "de", "van"):
        assert not _GEN_SUFFIX_RE.match(tok), tok


def test_the_strip_never_eats_the_whole_name():
    """A one-token name is the name, whatever it looks like."""
    assert strip_gen_suffix(["Jr"]) == ["Jr"]
    assert strip_gen_suffix(["II"]) == ["II"]
    assert strip_gen_suffix([]) == []


def test_an_ordinary_name_is_untouched():
    """The regression this could have caused: a surname that is not a suffix."""
    for raw, want in (("Shintaro Mochizuki", "mochizuki"),
                      ("Luca POW GBR", "pow"),
                      ("Dhakshineswar SURESH IND ANY", "suresh"),
                      ("[Q] Ye-Xin MA CHN", "ma"),
                      ("H. Nys", "nys"),
                      ("Alex de Minaur", "minaur")):
        assert carry_surname(raw) == want, raw
