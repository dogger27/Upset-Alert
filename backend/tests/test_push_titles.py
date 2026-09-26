"""Every push title fits on one line beside a timestamp.

"Changes to Your Draw" arrived as "Changes to Your…"; "4 Qualifiers Added" as
"4 Qualif…", at only eighteen characters, because the clock beside it had aged
from "12:30 AM" into "Yesterday, 10:45 PM". The budget shrinks as the
notification does, so a title that fitted on arrival is cut in Notification
Centre an hour later.

This has been fixed once before (88d519c7, Aug 2026) and drifted back, which is
why it is a test rather than a rule to remember. Anything new in push_content
is covered the moment it is added to CASES — and the sample() previews are
checked too, because a preview that says something the real builder never would
is worse than no preview.
"""
import pytest

from app.services import push_content as pc

CHANGE = {"kind": "replaced", "old_name": "Arthur Fils", "new_name": "Zizou Bergs",
          "new_entry_type": "LL", "old_entry_type": None, "bracket_position": 12,
          "opponent": "Carlos Alcaraz", "opponent_seed": 1, "affects_you": True}

DRAWS = [{"name": "Cincinnati Open", "gender": "M", "category": "ATP 1000",
          "id": 1, "closes_at": None, "changes": [CHANGE]}]


CASES = {
    "draw_release (1)": lambda: pc.draw_release(DRAWS[:1], "this week"),
    "draw_release (2)": lambda: pc.draw_release(DRAWS * 2, "this week"),
    "round_complete": lambda: pc.round_complete("R16", "Cincinnati Open", DRAWS, False),
    "round_complete (final)": lambda: pc.round_complete("Final", "Cincinnati Open", DRAWS, True),
    # The longest round word the labels produce, against the longest venue.
    "round_complete (R128)": lambda: pc.round_complete("R128", "Cincinnati Open", DRAWS, False),
    "draw_change": lambda: pc.draw_change(DRAWS, True),
    "qualifiers (1)": lambda: pc.qualifiers_added(DRAWS, True),
    "qualifiers (many)": lambda: pc.qualifiers_added(DRAWS * 4, True),
    "league_join": lambda: pc.league_join("dwightcharles", "BetaTesters", 3),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_title_fits(name):
    title = CASES[name]()["title"]
    assert len(title) <= pc.MAX_TITLE, f"{name}: {title!r} is {len(title)} chars"


SAMPLE_KEYS = [
    "draw_released", "round_standings", "tournament_end", "league_member_joined",
    "draw_changed", "qualifiers_added",
]


@pytest.mark.parametrize("key", SAMPLE_KEYS)
def test_sample_title_fits(key):
    title = pc.sample(key)["title"]
    assert len(title) <= pc.MAX_TITLE, f"{key}: {title!r} is {len(title)} chars"
