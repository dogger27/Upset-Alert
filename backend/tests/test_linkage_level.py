"""The nightly linkage report warns about what CHANGED.

It used to warn whenever there was any unpaired draw or any conflict — and
there always is: twenty-three future draws that cannot be paired until they are
played, three TML gaps in the women's grass season, four genuine TML
duplicates. So it warned every night with nothing to act on and became the
loudest line in /issues while saying the same thing each time.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def level_for(signals, prev, fuzzy=0):
    """The decision as link_all_async makes it, isolated from the session."""
    worse = sorted(k for k, v in signals.items() if v > prev.get(k, v))
    if fuzzy:
        worse.append("fuzzy matches")
    return ("warning" if (worse and prev) else "info"), worse


STEADY = {"stuck": 3, "unlinked": 6, "conflicts": 4, "bad_te_links": 0}


def test_the_steady_state_is_not_a_warning():
    """The exact numbers that warned every night for weeks."""
    level, worse = level_for(STEADY, STEADY)
    assert level == "info" and worse == []


def test_a_new_conflict_warns_and_says_so():
    level, worse = level_for({**STEADY, "conflicts": 5}, STEADY)
    assert level == "warning" and worse == ["conflicts"]


def test_a_draw_that_has_been_played_and_still_will_not_pair_warns():
    level, worse = level_for({**STEADY, "stuck": 4}, STEADY)
    assert level == "warning" and worse == ["stuck"]


def test_an_improvement_is_not_a_warning():
    """Fewer unlinked players than yesterday is good news, and good news is
    not an alarm."""
    level, worse = level_for({**STEADY, "unlinked": 2}, STEADY)
    assert level == "info" and worse == []


def test_a_fuzzy_match_warns_the_first_time():
    """A fuzzy match is a GUESS the linkage made — worth a human's eye the
    first time rather than the second, so it does not wait for a delta."""
    level, worse = level_for(STEADY, STEADY, fuzzy=1)
    assert level == "warning" and "fuzzy matches" in worse


def test_no_baseline_is_not_evidence_of_anything():
    """The first run after this ships has nothing to compare against, and must
    record a baseline rather than cry about every standing condition."""
    level, worse = level_for(STEADY, {})
    assert level == "info"
    # ...and with a fuzzy match it still holds: no baseline, no alarm.
    level, _ = level_for(STEADY, {}, fuzzy=1)
    assert level == "info"
