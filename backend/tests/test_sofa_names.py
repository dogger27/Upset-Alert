"""Sofascore's spelling, kept and preferred; Wikipedia's kept for the draw.

The tours print the Latinisation Sofascore uses ("Aleksandr Shevchenko");
Wikipedia's draw has "Alexander". A reader should see the former, and a
sheet should be matched against both (owner, 2026-09-17: "demote Wikipedia
wherever possible").
"""
from types import SimpleNamespace

from app.models.tournament import DrawEntry
from app.schemas.tournament import DrawEntryOut
from app.services.schedule import _fold, fold_index
from app.services.sofascore_results import sofa_names_in_event


def test_display_name_prefers_sofascore_and_falls_back_to_the_draw():
    e = DrawEntry(name="Alexander Shevchenko", nationality="KAZ", bracket_position=1)
    assert e.display_name == "Alexander Shevchenko"
    e.sofa_name = "Aleksandr Shevchenko"
    assert e.display_name == "Aleksandr Shevchenko"


def test_the_schema_serialises_the_display_name():
    obj = SimpleNamespace(id=1, name="Alexander Shevchenko", sofa_name="Aleksandr Shevchenko",
                          display_name="Aleksandr Shevchenko", nationality="KAZ", seed=None,
                          entry_type=None, bracket_position=1, ranking=90, seed_week_ranking=None,
                          date_of_birth=None, elo_rank=None, te_slug=None)
    assert DrawEntryOut.model_validate(obj).name == "Aleksandr Shevchenko"
    bare = SimpleNamespace(**{**obj.__dict__, "sofa_name": None, "display_name": "Alexander Shevchenko"})
    assert DrawEntryOut.model_validate(bare).name == "Alexander Shevchenko"


def test_every_spelling_leads_to_the_entry():
    idx = fold_index([(4783, "Alexander Shevchenko", "Aleksandr Shevchenko"), (4782, "Dino Prižmić", None)])
    assert idx[_fold("Aleksandr SHEVCHENKO")] == [4783]
    assert idx[_fold("Alexander Shevchenko")] == [4783]
    assert idx[_fold("Dino PRIZMIC")] == [4782]
    # The same spelling twice is one id, once.
    assert fold_index([(1, "A B", "A B")])[_fold("A B")] == [1]


def test_names_in_an_event_singles_and_doubles():
    ev = {"homeTeam": {"id": 11, "name": "Aleksandr Shevchenko"},
          "awayTeam": {"id": 22, "name": "Dino Prizmic"}}
    assert sofa_names_in_event(ev) == {11: "Aleksandr Shevchenko", 22: "Dino Prizmic"}
    dbl = {"homeTeam": {"id": 900, "name": "Hsieh S.-W. / Ostapenko J.",
                        "subTeams": [{"id": 1, "name": "Su-Wei Hsieh"}, {"id": 2, "name": "Jelena Ostapenko"}]},
           "awayTeam": {"id": 901, "name": "Kempen / Panova", "subTeams": [{"id": 3, "name": "Julia Kempen"}]}}
    assert sofa_names_in_event(dbl) == {1: "Su-Wei Hsieh", 2: "Jelena Ostapenko", 3: "Julia Kempen"}
    assert sofa_names_in_event({}) == {}
