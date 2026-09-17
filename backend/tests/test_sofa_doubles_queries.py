"""Finding a doubles event by name, and hearing a proxy refuse the tunnel.

Sofascore names the SP Open "WTA Sao Paulo, Brazil Women, Singles"; a search
for the whole string returns the singles alone, and the doubles resolver gave
up in silence — a week of doubles with no scores (2026-09-17). And the
residential proxy answering CONNECT with 402 was classified transient and
logged at debug, so nobody saw the ban fallback was gone.
"""
from app.services.sofascore import proxy_refused_tunnel
from app.services.sofascore_doubles import doubles_queries


def test_a_singles_suffixed_name_searches_for_doubles_first():
    q = doubles_queries("WTA Sao Paulo, Brazil Women, Singles", "SP Open")
    assert q == ["WTA Sao Paulo, Brazil Women, Doubles", "WTA Sao Paulo, Brazil Women", "SP Open"]


def test_an_old_style_name_goes_through_unchanged():
    assert doubles_queries("Guadalajara Open", "Guadalajara Open") == ["Guadalajara Open"]
    assert doubles_queries("Cincinnati", "Cincinnati Open") == ["Cincinnati", "Cincinnati Open"]


def test_nothing_to_search_for():
    assert doubles_queries("", None) == []
    assert doubles_queries("(2026)", "") == []


def test_the_proxy_refusing_the_tunnel_is_recognised():
    assert proxy_refused_tunnel(Exception("Failed to perform, curl: (7) CONNECT tunnel failed, response 402. See https://curl.se/"))
    assert proxy_refused_tunnel(Exception("CONNECT tunnel failed, response 407"))
    assert not proxy_refused_tunnel(Exception("Failed to perform, curl: (28) Operation timed out"))
    assert not proxy_refused_tunnel(Exception("403 on /event/1"))
