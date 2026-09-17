"""The inferred seed of a doubles pair (owner, 2026-09-17): the seeds keep
their number, the unseeded follow by the sum of their two doubles rankings at
the seeding week, equal sums share a rank, and a pair the rankings cannot
price gets no badge rather than a guess. Plus the Tennis Explorer doubles
list's own shapes: the `?t=doubles` page and the `?type=doubles` player href.
"""
from datetime import date

from app.services.doubles_rank import rank_pairs
from app.services.rankings import _TE_SLUG_RE, _te_params


def test_seeds_keep_their_number_and_the_unseeded_follow_by_sum():
    pairs = [
        ("siniakova/townsend", 1, 3),
        ("errani/paolini", 2, 12),
        ("kudermetova/mertens", None, 40),
        ("stearns/stephens", None, 180),
        ("frech/jovic", None, 95),
    ]
    got = rank_pairs(pairs)
    assert got["siniakova/townsend"] == 1
    assert got["errani/paolini"] == 2
    assert got["kudermetova/mertens"] == 3
    assert got["frech/jovic"] == 4
    assert got["stearns/stephens"] == 5


def test_equal_sums_share_a_rank_and_the_next_skips():
    got = rank_pairs([("a", 1, 5), ("b", None, 50), ("c", None, 50), ("d", None, 60)])
    assert got == {"a": 1, "b": 2, "c": 2, "d": 4}


def test_a_pair_without_a_sum_gets_no_rank():
    got = rank_pairs([("a", None, 30), ("b", None, None), ("c", 4, None)])
    assert got == {"a": 5, "c": 4}          # the unseeded count from the highest seed seen


def test_no_seeds_at_all_numbers_from_one():
    got = rank_pairs([("x", None, 90), ("y", None, 20)])
    assert got == {"y": 1, "x": 2}


def test_te_doubles_href_yields_the_slug():
    assert _TE_SLUG_RE.match("/player/heliovaara/?type=doubles").group(1) == "heliovaara"
    assert _TE_SLUG_RE.match("/player/sinner-8b8e8/").group(1) == "sinner-8b8e8"
    assert _TE_SLUG_RE.match("/ranking/atp-men/") is None


def test_te_doubles_page_params():
    assert _te_params(date(2026, 9, 1), doubles=True, page=2) == {"date": "2026-09-01", "t": "doubles", "page": 2}
    assert _te_params(None, doubles=False, page=1) == {"page": 1}
