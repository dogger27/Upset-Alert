"""Finding a doubles event by name, and hearing a proxy refuse the tunnel.

Sofascore names the SP Open "WTA Sao Paulo, Brazil Women, Singles"; a search
for the whole string returns the singles alone, and the doubles resolver gave
up in silence — a week of doubles with no scores (2026-09-17). And the
residential proxy answering CONNECT with 402 was classified transient and
logged at debug, so nobody saw the ban fallback was gone.
"""
from app.services.sofascore import proxy_refused_tunnel
from app.services.sofascore_doubles import doubles_queries, pick_doubles_event


def test_a_singles_suffixed_name_searches_for_doubles_first():
    q = doubles_queries("WTA Sao Paulo, Brazil Women, Singles", "SP Open")
    assert q == ["WTA Sao Paulo, Brazil Women, Doubles", "WTA Sao Paulo, Brazil Women", "SP Open"]


def test_a_plain_name_is_searched_in_its_doubles_form_first():
    # Singapore: "Singapore" alone never surfaces "Singapore, Doubles".
    assert doubles_queries("Singapore", "Singapore Open") == ["Singapore, Doubles", "Singapore", "Singapore Open"]
    assert doubles_queries("Guadalajara Open", "Guadalajara Open") == ["Guadalajara Open, Doubles", "Guadalajara Open"]


def test_the_exact_doubles_name_beats_the_first_hit():
    rows = [
        {"id": 2677, "name": "Tour Finals Singapore, Doubles", "category": {"name": "WTA"}},
        {"id": 24725, "name": "Singapore, Doubles", "category": {"name": "WTA"}},
        {"id": 16616, "name": "Singapore, Doubles", "category": {"name": "ATP"}},
    ]
    assert pick_doubles_event(rows, "WTA", "Singapore, Doubles") == 24725
    assert pick_doubles_event(rows, "ATP", "Singapore, Doubles") == 16616
    # No exact name: the old first-match rule, on the right tour.
    assert pick_doubles_event(rows, "WTA", "Somewhere, Doubles") == 2677
    assert pick_doubles_event([], "WTA", "x") is None


def test_nothing_to_search_for():
    assert doubles_queries("", None) == []
    assert doubles_queries("(2026)", "") == []


def test_the_proxy_refusing_the_tunnel_is_recognised():
    assert proxy_refused_tunnel(Exception("Failed to perform, curl: (7) CONNECT tunnel failed, response 402. See https://curl.se/"))
    assert proxy_refused_tunnel(Exception("CONNECT tunnel failed, response 407"))
    assert not proxy_refused_tunnel(Exception("Failed to perform, curl: (28) Operation timed out"))
    assert not proxy_refused_tunnel(Exception("403 on /event/1"))
