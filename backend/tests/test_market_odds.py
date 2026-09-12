"""The market yardstick: prices turned into probabilities, and rows matched
to the record by names printed two different ways."""
import pytest

from app.services.history.odds import (devig, market_name, names_match, pick_price, record_name)


def test_devig_removes_the_bookmakers_cut():
    # 1.50 / 2.50 imply 0.667 + 0.400 = 1.067 — the 6.7% is the margin.
    p = devig(1.50, 2.50)
    assert p == pytest.approx(0.6667 / 1.0667, abs=1e-4)
    # A fair two-way market comes back unchanged.
    assert devig(2.0, 2.0) == pytest.approx(0.5)
    # Antisymmetric: the two sides sum to one.
    assert devig(1.4, 3.1) + devig(3.1, 1.4) == pytest.approx(1.0)


def test_devig_refuses_impossible_prices():
    for bad in ((None, 2.0), (2.0, None), (1.0, 2.0), (0, 5), ("x", 2.0), (2.0, 0.5)):
        assert devig(*bad) is None


def test_pick_price_prefers_the_best_supported_column():
    row = {"AvgW": 1.8, "AvgL": 2.1, "B365W": 1.75, "B365L": 2.2, "PSW": 1.83, "PSL": 2.05}
    assert pick_price(row) == (1.8, 2.1, "average across books")
    # The average missing: Bet365 next.
    assert pick_price({"B365W": 1.75, "B365L": 2.2})[2] == "Bet365"
    # Only Pinnacle: still usable.
    assert pick_price({"PSW": 1.83, "PSL": 2.05})[2] == "Pinnacle"
    # Nothing priced, or a nonsense price.
    assert pick_price({"MaxW": 2.0, "MaxL": 2.0}) == (None, None, None)
    assert pick_price({"AvgW": 1.0, "AvgL": 0}) == (None, None, None)


def test_the_initial_is_the_last_letter_not_the_first():
    """tennis-data prints "O Connell C." — three tokens, and the initial is C."""
    sur, ini = market_name("O Connell C.")
    assert ini == "c" and "connell" in sur
    assert market_name("Zverev A.") == (frozenset({"zverev"}), "a")
    assert market_name("Ugo Carabelli C.") == (frozenset({"ugo", "carabelli"}), "c")


def test_record_names_split_the_other_way_round():
    """TennisMyLife prints the given names first."""
    assert record_name("Alexander Zverev") == (frozenset({"zverev"}), "a")
    assert record_name("Camilo Ugo Carabelli") == (frozenset({"ugo", "carabelli"}), "c")
    assert record_name("") == (frozenset(), "")


def test_names_match_across_the_two_forms_including_compound_surnames():
    assert names_match(market_name("Zverev A."), record_name("Alexander Zverev"))
    # A compound surname the spreadsheet abbreviates differently.
    assert names_match(market_name("Mpetshi G."), record_name("Giovanni Mpetshi Perricard"))
    assert names_match(market_name("Ugo Carabelli C."), record_name("Camilo Ugo Carabelli"))
    assert names_match(market_name("O Connell C."), record_name("Christopher O Connell"))
    # Different people are not matched, even sharing an initial.
    assert not names_match(market_name("Zverev A."), record_name("Alexander Bublik"))
    # Same surname, contradicting initials — the two Cerundolos, or two Zverevs.
    assert not names_match(market_name("Cerundolo J."), record_name("Francisco Cerundolo"))
    # An unknown initial does not veto a surname match.
    assert names_match((frozenset({"sinner"}), ""), record_name("Jannik Sinner"))
