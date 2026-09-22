"""One email per problem, and a subject no client cuts in half.

The owner, 2026-09-23: "Do not send me two emails for: Issue detected and
issue healed. Just send ONE: A detected issue has been healed. OR anything
that REALLY and TRULY needs my attention, add this in subject: '** FEEDBACK
NEEDED **: (short desc)'. Make sure you NEVER send an email whose subject gets
cut off in Gmail."

Two senders had to agree for that to hold: the self-healer, which mails its
verdict (selfheal/watch.sh, notify.sh), and this alerter, which mailed the
same problem the moment it was logged. The alerter now holds a signature back
until it has outlived the healer's reach, so a fixed problem produces the
healer's single line and nothing else.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.alerts import ALERT_HEAL_GRACE_MINUTES, ALERT_QUIET_HOURS
from app.services.email import SUBJECT_MAX, subject_line


# ── the subject rule ──────────────────────────────────────────────────────

REAL_SUBJECTS = [
    "A detected issue has been healed",
    "** FEEDBACK NEEDED **: self-heal hit the usage limit",
    "** FEEDBACK NEEDED **: self-heal could not finish",
    "** FEEDBACK NEEDED **: 3 issues (2 errors and 1 warning)",
    "** FEEDBACK NEEDED **: slot_unconfirmed fired inside its own fix window",
    "Round of 16 Complete: 2026 Korea Open presented by Someone WTA500",
    "One more draw is live — 2026 China Open (tennis) Women's singles",
    "OOP rev 2, Mon 22 Sep: Korea Open — verified",
    "Final Standings: 2026 Rolex Shanghai Masters ATP1000",
    "Verify your Upset Alert email",
]


@pytest.mark.parametrize("raw", REAL_SUBJECTS)
def test_no_subject_we_send_can_be_cut_off(raw):
    assert len(subject_line(raw)) <= SUBJECT_MAX


@pytest.mark.parametrize("raw", REAL_SUBJECTS)
def test_a_shortened_subject_still_reads_as_words(raw):
    out = subject_line(raw)
    assert out == out.strip()
    assert "…" not in out and "..." not in out, "an ellipsis is a cut-off admitted"
    if len(out) < len(" ".join(raw.split())):
        assert not out.endswith(("-", ":", ",", ";", "(", "—", "–")), out
        assert out.split(" ")[-1].lower() not in {
            "a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or",
            "the", "to", "with", "presented"}, out


def test_the_head_is_what_survives_not_the_tail():
    """An earlier draft dropped everything after the separator, which turned
    "Round of 16 Complete: 2026 Korea Open" into "Round of 16 Complete" — the
    reader lost WHICH event, the half they cannot guess."""
    out = subject_line("Round of 16 Complete: 2026 Korea Open presented by Someone WTA500")
    assert out.startswith("Round of 16 Complete")
    assert "Korea Open" in out


def test_a_subject_that_already_fits_is_left_exactly_alone():
    for s in ("A detected issue has been healed", "Welcome to Upset Alert!"):
        assert subject_line(s) == s


def test_whitespace_is_collapsed_not_counted():
    assert subject_line("  two   spaces  ") == "two spaces"


def test_one_unbroken_monster_word_is_still_cut_to_the_limit():
    out = subject_line("x" * 200)
    assert len(out) == SUBJECT_MAX


def test_nothing_is_a_subject_of_nothing():
    assert subject_line("") == ""
    assert subject_line(None) == ""


# ── the words the owner asked for ─────────────────────────────────────────

def test_the_healed_mail_says_exactly_what_was_asked_for():
    """watch.sh's title for a fix and for a fixed recurrence, which is the
    one email a healed problem produces."""
    assert subject_line("A detected issue has been healed") == "A detected issue has been healed"


def test_anything_needing_the_owner_is_marked_in_the_subject():
    from app.services.email import _headline
    headline = _headline("Failed to refresh 'Korea Open': ReadTimeout on the singles page",
                         limit=SUBJECT_MAX - 26)
    subject = subject_line(f"** FEEDBACK NEEDED **: {headline}")
    assert subject.startswith("** FEEDBACK NEEDED **: ")
    assert len(subject) <= SUBJECT_MAX
    assert len(subject) > len("** FEEDBACK NEEDED **: "), "the description survived"


# ── the grace that makes it ONE email ─────────────────────────────────────

def _survives(first_seen_min_ago, last_seen_min_ago, now=None):
    """The alerter's own test, in the shape scan_and_alert applies it."""
    now = now or datetime.now(timezone.utc)
    grace = timedelta(minutes=ALERT_HEAL_GRACE_MINUTES)
    oldest = now - timedelta(minutes=first_seen_min_ago)
    newest = now - timedelta(minutes=last_seen_min_ago)
    if (now - oldest) < grace:
        return False
    if (now - newest) > grace:
        return False
    return True


def test_a_problem_the_fixer_is_still_holding_is_not_mailed_yet():
    """Logged ten minutes ago: the healer has not had its four passes."""
    assert _survives(10, 10) is False


def test_a_problem_that_stopped_is_never_mailed_from_here():
    """Healed, or a blip. Either way the healer's own mail is the only one —
    which is the whole point of the grace."""
    assert _survives(240, 120) is False


def test_a_problem_still_happening_after_the_grace_is_the_owners():
    assert _survives(240, 5) is True


def test_the_grace_is_longer_than_the_healers_reach_and_shorter_than_quiet():
    """Four passes of a ten-minute watcher, and well inside the six hours
    after which a signature is considered gone."""
    assert ALERT_HEAL_GRACE_MINUTES >= 40
    assert ALERT_HEAL_GRACE_MINUTES < ALERT_QUIET_HOURS * 60
