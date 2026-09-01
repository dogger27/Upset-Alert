"""Compact round labels — R128 / R64 / R32 / R16 / QF / SF / F.

The scoreboard forms, for places with no room for a sentence: the Lock Screen
card, a phone's round strip, a chip in a list. `Draw.round_name()` keeps
producing the long forms ("Round of 128", "Quarterfinals") because a page has
room for them and they are what a bracket column header should say.

Note there is a THIRD wording in `notifications.py::_email_round_label`, which
turns "Quarterfinals" into "Quarter-Finals" rather than "QF". That is
deliberate and stays: an email subject line is prose, and "QF" in a sentence
reads like a typo. Three renderings of one concept is two too many to invent by
accident, so anything new should reuse one of these rather than add a fourth.
"""

import re

_PATTERNS = [
    (re.compile(r"round of (\d+)", re.I), lambda m: f"R{m.group(1)}"),
    (re.compile(r"quarter", re.I), lambda m: "QF"),
    (re.compile(r"semi", re.I), lambda m: "SF"),
    (re.compile(r"^final", re.I), lambda m: "F"),
    (re.compile(r"third place|3rd place", re.I), lambda m: "3rd"),
    (re.compile(r"qualifying round (\d+)", re.I), lambda m: f"Q{m.group(1)}"),
    (re.compile(r"qualifying", re.I), lambda m: "Q"),
]


def compact_round(name: str) -> str:
    """"Round of 128" -> "R128"; "Quarterfinals" -> "QF".

    Unknown wording is returned UNCHANGED rather than truncated: a label this
    function does not recognise is more useful whole than clipped to something
    that looks like a different round.
    """
    if not name:
        return ""
    for pattern, fn in _PATTERNS:
        m = pattern.search(name)
        if m:
            return fn(m)
    return name
