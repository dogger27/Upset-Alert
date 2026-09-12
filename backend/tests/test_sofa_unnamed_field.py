"""A bracket shape with nobody in it is not a resolution failure.

Sofascore publishes the cup tree before the names: SP Open 2026 came back two
days before play as thirty teams called R16P1, R16P2 … every one of them
`disabled`. Nothing can match a placeholder, so the coverage check's
"a tournament id but not one player resolved" — written on the premise that an
id existing means the bracket is published — fired for the ordinary state of a
draw nobody has named yet.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.sofascore import field_is_unnamed, _is_placeholder   # noqa: E402


def test_the_real_sp_open_payload_is_recognised():
    field = [{"id": 393276, "name": "R16P1", "disabled": True},
             {"id": 393277, "name": "R16P2", "disabled": True},
             {"id": 393278, "name": "R16P3", "disabled": True}]
    assert field_is_unnamed(field)


def test_a_named_field_is_not():
    field = [{"id": 1, "name": "Marta Kostyuk"}, {"id": 2, "name": "Iva Jovic"}]
    assert not field_is_unnamed(field)


def test_one_real_name_among_placeholders_is_a_field():
    """Names arrive gradually, and the moment one is real the draw is joinable
    — so this must not keep reporting "unnamed" and suppress a real warning."""
    field = [{"id": 1, "name": "R16P1", "disabled": True},
             {"id": 2, "name": "Marta Kostyuk"}]
    assert not field_is_unnamed(field)


def test_an_empty_field_is_a_different_state():
    """`cup tree empty` has its own message — "not published yet" rather than
    "published without names" — so this must not claim it."""
    assert not field_is_unnamed([])
    assert not field_is_unnamed(None)


def test_the_placeholder_shapes_seen_in_the_wild():
    assert _is_placeholder({"name": "R16P4", "disabled": True})
    assert _is_placeholder({"name": "r32p12"})            # case, wider round
    assert _is_placeholder({"name": "Qualifier"})
    assert _is_placeholder({"name": "TBD"})
    assert _is_placeholder({"name": "Bye"})
    # `disabled` alone is enough, whatever it is called.
    assert _is_placeholder({"name": "Someone Real", "disabled": True})
    assert not _is_placeholder({"name": "Taylor Townsend"})
    # A real player whose name merely starts like a placeholder.
    assert not _is_placeholder({"name": "R. Zarazúa"})
