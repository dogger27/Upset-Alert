"""
Two occurrences of one problem must be ONE alert signature.

WHY THIS IS WORTH A TEST: log_fingerprint() normalises digits out of a message
and nothing else, so an id or a count in the line is harmless and a NAME is
not. Rain hit SP Open on 2026-09-15, the tour reissued three sheets in 27
hours, each pulled a different match off the page, and each named the players
it pulled — three signatures for one situation. Three rows in the admin panel
where there should have been one with a count, three of the day's three alert
slots, and three wake-ups for the self-healing watcher, which investigated all
three and correctly changed nothing each time.

Nothing raises when this regresses. The alert still sends; it just sends again,
and the only symptom is a phone going off at 2am.
"""
from app.services.alerts import log_fingerprint


def _pull(n, tournament, day, doc):
    """The message ingest_document logs when a sheet stops printing a slot."""
    return (f"{n} slot(s) pulled from {tournament} on {day} by document {doc}")


def test_reissues_of_one_day_are_one_signature():
    # The three that actually fired, by their real documents and counts.
    first = log_fingerprint("warning", "order_of_play", _pull(6, "SP Open", "2026-09-15", 264))
    second = log_fingerprint("warning", "order_of_play", _pull(2, "SP Open", "2026-09-16", 267))
    third = log_fingerprint("warning", "order_of_play", _pull(1, "SP Open", "2026-09-16", 268))
    assert first == second == third, (
        "a reissue is the same problem: the count, the day and the document id "
        "are all digits, and digits are normalised away"
    )


def test_a_different_tournament_is_a_different_signature():
    # The collapse must not go so far as to hide a second tournament: that is
    # two sheets to go and look at, which is the line log_fingerprint draws.
    sp = log_fingerprint("warning", "order_of_play", _pull(2, "SP Open", "2026-09-16", 267))
    guad = log_fingerprint("warning", "order_of_play",
                           _pull(2, "Guadalajara Open", "2026-09-16", 267))
    assert sp != guad


def test_the_pulled_slots_are_not_in_the_message():
    """The guard that keeps the fix in place.

    Reading the source rather than the log, because the point is a property of
    the line as written: whoever adds "and here is what was pulled" to the
    message will pass every other test in the suite.
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "app" / "services" / "schedule.py"
    text = src.read_text()
    for marker in ("slot(s) pulled from", "were dropped by the parser"):
        assert marker in text, f"log line moved or reworded: {marker!r}"
        # The 400 characters after the marker cover the f-string and its detail
        # dict; a join of names inside the MESSAGE would land in there.
        window = text[text.index(marker): text.index(marker) + 400]
        head = window.split("{\"tournament_id\"")[0]
        assert ".join(" not in head, (
            f"{marker!r} puts variable text in the message — names defeat the "
            "fingerprint, so this belongs in detail_json"
        )
