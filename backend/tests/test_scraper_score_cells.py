"""Wikipedia score cells → our "6(5)" spelling, whatever the editor typed."""
from app.services.scraper import _parse_score_value as p


def test_closed_sup():
    assert p("6<sup>5</sup>") == "6(5)"
    assert p("'''7<sup>7</sup>'''") == "7(7)"


def test_unclosed_sup_is_the_same_score():
    # Badosa–Gauff, US Open 2026: the editor never closed the tag. Wikipedia
    # renders it as a superscript all the same; we read "65" for an evening.
    assert p("6<sup>5") == "6(5)"
    assert p("'''7<sup>7'''") == "7(7)"


def test_plain_cells():
    assert p("6") == "6"
    assert p("'''6'''") == "6"
    assert p(" ") is None
    assert p("6<sup>10</sup>") == "6(10)"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
